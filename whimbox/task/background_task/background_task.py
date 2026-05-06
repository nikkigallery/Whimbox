import time
import threading
from enum import Enum
from whimbox.interaction.interaction_core import itt
from whimbox.ui.ui_assets import *
from whimbox.action.fishing import FishingTask
from whimbox.action.skip_dialog import SkipDialogTask
from whimbox.common.logger import logger
from whimbox.common.cvars import has_foreground_task
from whimbox.common.utils.img_utils import crop
from whimbox.task.task_template import STATE_TYPE_SUCCESS, STATE_TYPE_STOP
from whimbox.common.cvars import current_stop_flag
from whimbox.common.keybind import keybind
from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.common.utils.img_utils import process_with_hsv_limit, similar_img
import cv2
from pynput import mouse
from whimbox.ability.ability import ability_manager
from whimbox.ability.cvar import ABILITY_NAME_FLOURISH, ABILITY_NAME_INSECT
from whimbox.config.config import global_config
from whimbox.config.default_config import DEFAULT_CONFIG
from whimbox.tool_invocation_coordinator import tool_invocation_coordinator


class BackgroundFeature(Enum):
    """后台功能枚举"""
    AUTO_FISHING = "auto_fishing"
    AUTO_DIALOGUE = "auto_dialogue"
    AUTO_PICKUP = "auto_pickup"
    AUTO_CLEAR = "auto_clear"
    AUTO_FLOURISH = "auto_flourish"
    AUTO_FLOURAL = "auto_floral"


class FeatureConfig:
    """功能配置"""
    def __init__(self, enabled: bool = False, interval: int = 1):
        """
        Args:
            enabled: 是否启用
            interval: 执行间隔(轮数),每N轮执行一次
        """
        self.enabled = enabled
        self.interval = interval
        self.counter = 0  # 当前计数器
    
    def should_execute(self) -> bool:
        """判断是否应该执行"""
        if not self.enabled:
            return False
        self.counter += 1
        if self.counter >= self.interval:
            self.counter = 0
            return True
        return False
    
    def reset_counter(self):
        """重置计数器"""
        self.counter = 0


class BackgroundTaskManager:
    """后台任务管理器 - 单例模式"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 后台任务实例
        self.background_task = None
        self.background_thread = None
        self.is_game_started = False
        self.is_game_shape_ok = False
        
        interval_map = {
            BackgroundFeature.AUTO_PICKUP: 1,
            BackgroundFeature.AUTO_CLEAR: 3,
        }
        self.feature_configs = {
            feature: FeatureConfig(enabled=False, interval=interval_map.get(feature, 5))
            for feature in self._iter_configured_features()
        }
        
        # 从配置文件加载状态（但不自动启动任务）
        self._load_from_config()
    
    def set_feature_enabled(self, feature: BackgroundFeature, enabled: bool):
        """设置功能开关
        
        Args:
            feature: 功能类型
            enabled: 是否启用
        """
        with self._lock:
            if feature in self.feature_configs:
                self.feature_configs[feature].enabled = enabled
                self.feature_configs[feature].reset_counter()
                # 保存到配置文件
                self._save_to_config(feature, enabled)
    
    def is_feature_enabled(self, feature: BackgroundFeature) -> bool:
        """检查功能是否启用"""
        config = self.feature_configs.get(feature)
        return config.enabled if config else False
    
    def get_feature_config(self, feature: BackgroundFeature) -> FeatureConfig:
        """获取功能配置"""
        return self.feature_configs.get(feature)
    
    def _load_from_config(self):
        """从配置文件加载状态"""
        try:
            loaded_states = {}
            for feature in self._iter_configured_features():
                enabled = global_config.get_bool("BackgroundTask", feature.value, False)
                self.feature_configs.setdefault(feature, FeatureConfig()).enabled = enabled
                loaded_states[feature.value] = enabled

            logger.info(f"从配置文件加载后台任务状态: {loaded_states}")
        except Exception as e:
            logger.warning(f"加载后台任务配置失败: {e}")

    def _iter_configured_features(self):
        """Return implemented background features in default-config order."""
        for key in (DEFAULT_CONFIG.get("BackgroundTask") or {}):
            try:
                yield BackgroundFeature(key)
            except ValueError:
                logger.warning(f"BackgroundTask config key has no implementation: {key}")
    
    def _save_to_config(self, feature: BackgroundFeature, enabled: bool):
        """保存单个功能状态到配置文件"""
        try:
            # 将枚举值转换为配置键名
            config_key = feature.value  # auto_fishing, auto_dialogue, auto_pickup
            
            global_config.set("BackgroundTask", config_key, str(enabled).lower())
            global_config.save()
            logger.debug(f"已保存后台任务配置: {config_key}={enabled}")
        except Exception as e:
            logger.error(f"保存后台任务配置失败: {e}")
    
    def start_background_task(self):
        """启动后台任务"""
        with self._lock:
            if self.background_task is not None and self.background_task.is_running():
                logger.warning("后台任务已在运行")
                return False
            
            # 创建新的后台任务
            self.background_task = BackgroundTask(self)
            
            # 在新线程中运行
            self.background_thread = threading.Thread(
                target=self.background_task.run,
                daemon=True
            )
            self.background_thread.start()
            logger.info("后台任务已启动")
            return True
    
    def stop_background_task(self):
        """停止后台任务"""
        with self._lock:
            if self.background_task is None:
                logger.warning("后台任务未运行")
                return False
            
            self.background_task.stop()
            logger.info("后台任务已停止")
            return True
    
    def is_running(self) -> bool:
        """检查后台任务是否在运行"""
        return self.background_task is not None and self.background_task.is_running()


class BackgroundTask:
    """后台任务 - 自动检测画面并执行对应功能"""
    
    def __init__(self, manager: BackgroundTaskManager):
        self.manager = manager
        self.check_interval = 0.1  # 画面检测间隔（秒）
        if global_config.get_bool("Path", "high_performance_pc", False):
            self.check_interval = 0.02
        self.was_paused = False  # 上一次循环是否处于暂停状态
        self.stop_event = threading.Event()  # 停止事件
        self.mouse_listener = None
        self._start_mouse_listener()

        self.is_auto_click = False
        self.need_flourish = False
        self.need_floral = False

    def on_mouse_click(self, x, y, button, pressed):
        if (not self.was_paused) and (button == mouse.Button.right) and pressed and (not self.is_auto_click):
            # 启停萤火虫套能力
            flourish_config = self.manager.get_feature_config(BackgroundFeature.AUTO_FLOURISH)
            if flourish_config and flourish_config.enabled and HANDLE_OBJ.is_foreground():
                if self.need_flourish:
                    self.need_flourish = False
                    itt.key_press(keybind.KEYBIND_SPRINT)
                else:
                    if ability_manager.get_current_ability() == ABILITY_NAME_FLOURISH:
                        self.need_flourish = True
            # 启停花套能力
            floral_config = self.manager.get_feature_config(BackgroundFeature.AUTO_FLOURAL)
            if floral_config and floral_config.enabled and HANDLE_OBJ.is_foreground():
                if self.need_floral:
                    self.need_floral = False
                else:
                    if ability_manager.get_current_ability() == ABILITY_NAME_INSECT:
                        self.need_floral = True

    def _create_mouse_listener(self):
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.daemon = True

    def _start_mouse_listener(self):
        if self.mouse_listener is None or not self.mouse_listener.is_alive():
            self._create_mouse_listener()
            self.mouse_listener.start()

    def _stop_mouse_listener(self):
        if self.mouse_listener is not None:
            try:
                self.mouse_listener.stop()
            finally:
                # Listener 线程停止后无法再次 start，清空以便重建
                self.mouse_listener = None

    def _resolve_session_id(self) -> str:
        """解析后台日志/子任务应归属的会话 ID。"""
        from whimbox.common.cvars import get_current_session_id
        sid = get_current_session_id()
        if sid and sid != "default":
            return sid
        try:
            from whimbox.session_manager import session_manager
            sessions = session_manager.list()
            if sessions:
                running = next((s for s in sessions if s.get("state") == "RUNNING"), None)
                if running and running.get("session_id"):
                    return running["session_id"]
                latest = sessions[-1].get("session_id")
                if latest:
                    return latest
        except Exception as e:
            logger.debug(f"后台任务解析 session_id 失败: {e}")
        return "default"

    def log_to_gui(self, msg, is_error=False, is_stopped=False, type="update_ai_message"):
        raw_message = msg
        if is_stopped:
            msg = f"🛑 {msg}"
            level = "info"
        else:
            if is_error:
                msg = f"❌ {msg}"
                level = "error"
            else:
                msg = f"✅ {msg}"
                level = "info"

        from whimbox.rpc_server import notify_event

        session_id = self._resolve_session_id()
        notify_event(
            "event.run.log",
            {
                "session_id": session_id,
                "run_id": f"background:{session_id}",
                "source": "background",
                "message": msg,
                "raw_message": raw_message,
                "level": level,
                "type": type,
            },
        )
        logger.info(msg)

    def _notify_background_status(
        self,
        *,
        session_id: str,
        phase: str,
        tool_id: str,
        detail: str = "",
        result: dict | None = None,
        error: str = "",
    ):
        from whimbox.rpc_server import notify_event

        payload = {
            "session_id": session_id,
            "run_id": f"background:{session_id}:{tool_id}",
            "source": "background",
            "phase": phase,
            "tool_id": tool_id,
        }
        if detail:
            payload["detail"] = detail
        if result is not None:
            payload["result"] = result
        if error:
            payload["error"] = error
        notify_event("event.run.status", payload)

    def _try_enter_background_tool(self, *, session_id: str, tool_id: str):
        owner = f"background:{session_id}:{tool_id}"
        return tool_invocation_coordinator.acquire_sync(
            resource_group="game_runtime",
            owner=owner,
            wait_policy="skip_if_busy",
        )

    def _leave_background_tool(self, *, session_id: str, tool_id: str) -> None:
        owner = f"background:{session_id}:{tool_id}"
        tool_invocation_coordinator.release(
            resource_group="game_runtime",
            owner=owner,
        )

    def stop(self):
        """停止后台任务"""
        self.stop_event.set()
    
    def is_running(self) -> bool:
        """检查是否在运行"""
        return not self.stop_event.is_set()
    
    def run(self):
        """持续检测画面并触发对应功能"""
        # 检查游戏窗口是否已存在，分辨率是否支持
        while not self.stop_event.is_set():
            if not HANDLE_OBJ.is_alive():
                time.sleep(1)
                HANDLE_OBJ.refresh_handle()
            else:
                self.manager.is_game_started = True
                break
        while not self.stop_event.is_set():
            shape_ok, _, _ = HANDLE_OBJ.check_shape()
            if not shape_ok:
                time.sleep(0.5)
            else:
                self.manager.is_game_shape_ok = True
                break
        logger.info("后台小工具开始运行")
        
        try:
            while not self.stop_event.is_set():
                # 检测是否有前台任务在运行
                if has_foreground_task():
                    # 有前台任务在运行，暂停后台任务
                    if not self.was_paused:
                        # 刚进入暂停状态
                        logger.info("检测到前台任务运行，后台小工具暂停")
                        self.was_paused = True
                        self._stop_mouse_listener()
                    time.sleep(1)
                    continue
                else:
                    # 没有前台任务
                    if self.was_paused:
                        # 刚从暂停状态恢复
                        logger.info("前台任务结束，后台小工具恢复运行")
                        self.was_paused = False
                        self._start_mouse_listener()
                
                # 检测各种画面状态
                try:
                    cap = itt.capture()
                    
                    # 检测采集状态 - 根据间隔执行
                    pickup_config = self.manager.get_feature_config(BackgroundFeature.AUTO_PICKUP)
                    if pickup_config and pickup_config.should_execute():
                        if self._detect_pickup_opportunity(cap):
                            # 快速按F连续采集
                            while True:
                                itt.key_press(keybind.KEYBIND_INTERACTION)
                                time.sleep(0.02)
                                cap = itt.capture()
                                if not self._detect_pickup_opportunity(cap):
                                    break

                    # 检测萤火虫套状态 - 根据间隔执行
                    flourish_config = self.manager.get_feature_config(BackgroundFeature.AUTO_FLOURISH)
                    if self.need_flourish and flourish_config and flourish_config.should_execute():
                        if ability_manager.check_current_ability(IconAbilityFlourish, cap):
                            self.is_auto_click = True
                            itt.right_click()
                            self.is_auto_click = False
                            time.sleep(0.3)

                    # 检测花套状态 - 根据间隔执行
                    floral_config = self.manager.get_feature_config(BackgroundFeature.AUTO_FLOURAL)
                    if self.need_floral and floral_config and floral_config.should_execute():
                        if ability_manager.check_current_ability(IconAbilityInsect, cap):
                            self.is_auto_click = True
                            itt.right_click()
                            self.is_auto_click = False
                            time.sleep(0.3)

                    # 检测清洁跳过状态
                    clear_config = self.manager.get_feature_config(BackgroundFeature.AUTO_CLEAR)
                    if clear_config and clear_config.should_execute():
                        if self._detect_clear_opportunity(cap):
                            itt.key_press(keybind.KEYBIND_INTERACTION)
                            # 清洁的跳过按钮和剧情动画的跳过按钮是一样的
                            # 所以判断按了F后，跳过按钮是否消失，如果没消失就一直等待，避免又检测到跳过按钮，不断按F
                            while not self.stop_event.is_set():
                                time.sleep(0.3)
                                if not itt.get_img_existence(IconSkip):
                                    break

                    # 检测钓鱼状态 - 根据间隔执行
                    fishing_config = self.manager.get_feature_config(BackgroundFeature.AUTO_FISHING)
                    if fishing_config and fishing_config.should_execute():
                        if self._detect_fishing_opportunity(cap):
                            self._execute_fishing()      
                    
                    # 检测对话状态 - 根据间隔执行
                    dialogue_config = self.manager.get_feature_config(BackgroundFeature.AUTO_DIALOGUE)
                    if dialogue_config and dialogue_config.should_execute():
                        if self._detect_dialogue_opportunity(cap):
                            self._execute_dialogue()
                            
                except Exception as e:
                    if not HANDLE_OBJ.is_alive():
                        time.sleep(10)
                        logger.info("游戏窗口已关闭，重新获取窗口句柄")
                        HANDLE_OBJ.refresh_handle()
                    else:
                        # 如果游戏最小化了
                        if "cannot reshape array" in str(e):
                            time.sleep(1)
                        else:
                            logger.error(f"后台小工具检测出错: {e}")
                            import traceback
                            traceback.print_exc()
                
                # 等待一段时间再检测
                time.sleep(self.check_interval)
        
        except Exception as e:
            logger.error(f"后台小工具运行出错: {e}")
        finally:
            logger.info("后台小工具已停止")
    
    def _detect_fishing_opportunity(self, cap) -> bool:
        """检测是否可以钓鱼"""
        cap = crop(cap, AreaFishingIcons.position)
        if itt.get_img_existence(IconFishingFinish, cap=cap):
            return True
        return False
    
    def _execute_fishing(self):
        """执行钓鱼任务"""
        from whimbox.common.cvars import current_session_id
        session_id = self._resolve_session_id()
        token = current_session_id.set(session_id)
        tool_id = "background.auto_fishing"
        acquire_result = self._try_enter_background_tool(session_id=session_id, tool_id=tool_id)
        if not acquire_result.acquired:
            logger.info("后台自动钓鱼跳过：game_runtime 正被前台占用")
            return
        self._notify_background_status(
            session_id=session_id,
            phase="started",
            tool_id=tool_id,
            detail="auto_fishing",
        )
        try:
            # 停止鼠标监听，避免干扰鼠标点击
            self._stop_mouse_listener()
            self.log_to_gui("检测到钓鱼界面，开始自动钓鱼", type="add_ai_message")
            self.log_to_gui("你可以按 " + global_config.get("Whimbox", "stop_key") + " 键，随时停止钓鱼")
            fishing_task = FishingTask(session_id=session_id)
            # 后台钓鱼直接调用 step2，不经过 rpc_server 的 task.stop 路径，
            # 这里显式补回停止热键绑定。
            fishing_task.add_hotkey(global_config.get("Whimbox", "stop_key"), fishing_task.task_stop)
            fishing_task.step2()
             # 因为不是完整的task运行流程，所以手动清除current_stop_flag
            current_stop_flag.set(None)
            if fishing_task.task_result.status == STATE_TYPE_SUCCESS:
                self.log_to_gui(f"自动钓鱼完成: {fishing_task.task_result.message}", type="finalize_ai_message")
                self._notify_background_status(
                    session_id=session_id,
                    phase="completed",
                    tool_id=tool_id,
                    result={"status": "success", "message": str(fishing_task.task_result.message or "")},
                )
            elif fishing_task.task_result.status == STATE_TYPE_STOP:
                self.log_to_gui(f"手动停止钓鱼", is_stopped=True, type="finalize_ai_message")
                self._notify_background_status(
                    session_id=session_id,
                    phase="cancelled",
                    tool_id=tool_id,
                    result={"status": "stop", "message": str(fishing_task.task_result.message or "手动停止")},
                )
                time.sleep(5) # 等待5秒，避免又检测到钓鱼界面，又开始自动钓鱼
            else:
                self.log_to_gui(f"自动钓鱼失败: {fishing_task.task_result.message}", type="finalize_ai_message")
                self._notify_background_status(
                    session_id=session_id,
                    phase="error",
                    tool_id=tool_id,
                    result={"status": "failed", "message": str(fishing_task.task_result.message or "自动钓鱼失败")},
                    error=str(fishing_task.task_result.message or "自动钓鱼失败"),
                )
        except Exception as e:
            logger.error(f"自动钓鱼出错: {e}")
            self._notify_background_status(
                session_id=session_id,
                phase="error",
                tool_id=tool_id,
                error=str(e),
            )
        finally:
            self._leave_background_tool(session_id=session_id, tool_id=tool_id)
            current_session_id.reset(token)
            self._start_mouse_listener()

    def _detect_dialogue_opportunity(self, cap) -> bool:
        """检测是否进入对话"""
        cap = crop(cap, IconSkipDialog.cap_posi)
        if itt.get_img_existence(IconSkipDialog, cap=cap):
            return True
        return False
    
    def _execute_dialogue(self):
        """执行对话任务"""
        from whimbox.common.cvars import current_session_id
        session_id = self._resolve_session_id()
        token = current_session_id.set(session_id)
        tool_id = "background.auto_dialogue"
        acquire_result = self._try_enter_background_tool(session_id=session_id, tool_id=tool_id)
        if not acquire_result.acquired:
            logger.info("后台自动对话跳过：game_runtime 正被前台占用")
            return
        self._notify_background_status(
            session_id=session_id,
            phase="started",
            tool_id=tool_id,
            detail="auto_dialogue",
        )
        try:
            # self.log_to_gui("检测到对话界面，开始自动对话", type="add_ai_message")
            skip_dialog_task = SkipDialogTask(session_id=session_id)
            skip_dialog_task.task_run()
            # self.log_to_gui(f"自动对话结束", type="finalize_ai_message")
            if skip_dialog_task.task_result.status == STATE_TYPE_STOP:
                self._notify_background_status(
                    session_id=session_id,
                    phase="cancelled",
                    tool_id=tool_id,
                    result={"status": "stop", "message": str(skip_dialog_task.task_result.message or "手动停止")},
                )
            elif skip_dialog_task.task_result.status == STATE_TYPE_SUCCESS:
                self._notify_background_status(
                    session_id=session_id,
                    phase="completed",
                    tool_id=tool_id,
                    result={"status": "success", "message": str(skip_dialog_task.task_result.message or "")},
                )
            else:
                self._notify_background_status(
                    session_id=session_id,
                    phase="error",
                    tool_id=tool_id,
                    result={"status": "failed", "message": str(skip_dialog_task.task_result.message or "自动对话失败")},
                    error=str(skip_dialog_task.task_result.message or "自动对话失败"),
                )
        except Exception as e:
            self._notify_background_status(
                session_id=session_id,
                phase="error",
                tool_id=tool_id,
                error=str(e),
            )
            raise
        finally:
            self._leave_background_tool(session_id=session_id, tool_id=tool_id)
            current_session_id.reset(token)

    def _detect_pickup_opportunity(self, cap) -> bool:
        """检测是否可以采集"""
        cap = crop(cap, AreaPickup.position)
        if itt.get_img_existence(IconPickupFeature, cap=cap):
            return True
        return False

    def _detect_clear_opportunity(self, cap) -> bool:
        """检测是否可以清洁跳过"""
        cap = crop(cap, IconSkip.cap_posi)
        if itt.get_img_existence(IconSkip, cap=cap):
            return True
        return False


# 全局后台任务管理器实例
background_manager = BackgroundTaskManager()
background_manager.start_background_task()

if __name__ == "__main__":
    # 测试代码
    manager = background_manager
    
    # 启用自动钓鱼
    manager.set_feature_enabled(BackgroundFeature.AUTO_FISHING, True)
    
    # 启动后台任务
    manager.start_background_task()
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop_background_task()
