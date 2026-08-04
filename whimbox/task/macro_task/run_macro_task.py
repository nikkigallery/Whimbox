from whimbox.task.task_template import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.scripts_manager import *
from whimbox.common.logger import logger
import time
from whimbox.common.scripts_manager import *
from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.common.timer_module import TimeoutTimer
import math

DEFAULT_TIMEOUT = 20
MIN_SMOOTH_DRAG_DURATION = 0.08
MIN_SMOOTH_DRAG_DISTANCE = 10

class RunMacroTask(TaskTemplate):
    """运行宏记录的任务"""
    
    def __init__(self, session_id, macro_filename: str, delay=0, check_stop_func=None):
        super().__init__(session_id=session_id, name="run_macro_task")
        self.check_stop_func = check_stop_func
        self.delay = delay
        self.macro_record = scripts_manager.query_macro(macro_filename, return_one=True)
        if not self.macro_record:
            raise ValueError(f"宏\"{macro_filename}\"不存在，请先下载该宏")
        if self.macro_record.info.version not in ("3.0", "3.1"):
            raise ValueError(f"宏版本不匹配，请更新宏（当前版本：{self.macro_record.info.version}）")
        self.is_play_music = False
        if self.macro_record.info.type == "乐谱":
            self.is_play_music = True

        self.current_step_index = 0
        self.pressing_keys = set()

    def _find_drag_release_step(self, steps: list[MacroStep], press_index: int):
        """查找可平滑执行的拖拽释放步骤。仅支持 press-gap...-release 简单序列。"""
        press_step = steps[press_index]
        if (
            press_step.type != "mouse"
            or press_step.action != "press"
            or not press_step.position
            or not press_step.key
        ):
            return None

        drag_duration = 0.0
        release_index = press_index + 1
        while release_index < len(steps):
            step = steps[release_index]
            if step.type == "gap":
                drag_duration += step.duration or 0
                release_index += 1
                continue

            if (
                step.type == "mouse"
                and step.action == "release"
                and step.key == press_step.key
                and step.position
            ):
                distance = math.dist(press_step.position, step.position)
                if (
                    drag_duration < MIN_SMOOTH_DRAG_DURATION
                    or distance < MIN_SMOOTH_DRAG_DISTANCE
                ):
                    return None
                return release_index, drag_duration

            return None

        return None

    def _execute_drag_step(self, press_step: MacroStep, release_step: MacroStep, drag_duration: float):
        """执行拖拽：瞬移到按下点，按住后平滑移动到释放点。"""
        itt.move_to(press_step.position)
        itt.key_down(press_step.key)
        self.pressing_keys.add(press_step.key)
        itt.move_to(release_step.position, smooth=True, smooth_duration=drag_duration)
        itt.key_up(release_step.key)
        self.pressing_keys.discard(release_step.key)

    def _execute_range(
        self,
        steps: list[MacroStep],
        start: int = 0,
        end: int | None = None,
        depth: int = 0,
    ):
        """递归执行指定范围，循环体可以继续包含循环。"""
        end = len(steps) if end is None else end
        i = start
        while i < end:
            if self.need_stop() or (self.check_stop_func and self.check_stop_func()):
                return

            step = steps[i]
            self.current_step_index = i
            if step.type == "loop":
                body_end = i + 1 + int(step.loop_steps or 0)
                for iteration in range(int(step.loop_count or 0)):
                    if self.need_stop() or (self.check_stop_func and self.check_stop_func()):
                        return
                    self.log_to_gui(
                        f"{'  ' * depth}循环第 {iteration + 1}/{step.loop_count} 次"
                    )
                    self._execute_range(steps, i + 1, body_end, depth + 1)
                i = body_end
                continue

            drag_release_info = self._find_drag_release_step(steps, i)
            if drag_release_info and drag_release_info[0] < end:
                release_index, drag_duration = drag_release_info
                self._execute_drag_step(step, steps[release_index], drag_duration)
                i = release_index + 1
                continue

            self._execute_step(step)
            i += 1

    def _execute_steps(self, steps: list[MacroStep]):
        """兼容旧调用入口。"""
        self._execute_range(steps)
    
    def _execute_step(self, step: MacroStep):
        """执行单个宏步骤"""
        try:
            if step.type == "gap":
                # 间隔等待
                if step.duration and step.duration > 0:
                    time.sleep(step.duration)
                    
            elif step.type == "keyboard":
                # 键盘操作
                if step.action == "press":
                    itt.key_down(step.key)
                    self.pressing_keys.add(step.key)
                elif step.action == "release":
                    itt.key_up(step.key)
                    self.pressing_keys.discard(step.key)
                    
            elif step.type == "mouse":
                # 鼠标按键操作
                if step.position:
                    # 移动到目标位置并点击
                    if step.action == "press":
                        itt.move_to(step.position)
                        itt.key_down(step.key)
                        self.pressing_keys.add(step.key)
                    elif step.action == "release":
                        itt.move_to(step.position)
                        itt.key_up(step.key)
                        self.pressing_keys.discard(step.key)
            
            elif step.type == "wait_game_page":
                # 等待某个特定游戏页面
                if step.target_game_page not in ui_page_dict:
                    raise Exception(f"不支持检测「{step.target_game_page}」页面")
                else:
                    timeout_timer = TimeoutTimer(DEFAULT_TIMEOUT)
                    is_timeout = False
                    while not ui_control.verify_page(ui_page_dict[step.target_game_page]): 
                        if timeout_timer.istimeout():
                            is_timeout = True
                            self.log_to_gui(f"等待进入「{step.target_game_page}」页面超时", is_error=True)
                            break
                        time.sleep(0.1)
                    if not is_timeout:
                        self.log_to_gui(f"检测到进入「{step.target_game_page}」页面")
            
            elif step.type == "wait_not_game_page":
                # 等待不再是特定游戏页面
                if step.target_game_page not in ui_page_dict:
                    raise Exception(f"不支持检测「{step.target_game_page}」页面")
                else:
                    timeout_timer = TimeoutTimer(DEFAULT_TIMEOUT)
                    is_timeout = False
                    while ui_control.verify_page(ui_page_dict[step.target_game_page]):
                        if timeout_timer.istimeout():
                            is_timeout = True
                            self.log_to_gui(f"等待退出「{step.target_game_page}」页面超时", is_error=True)
                            break
                        time.sleep(0.1)
                    if not is_timeout:
                        self.log_to_gui(f"检测到退出「{step.target_game_page}」页面")
            
            elif step.type == "goto_game_page":
                # 前往某个特定游戏页面
                if step.target_game_page not in ui_page_dict:
                    raise Exception(f"不支持前往「{step.target_game_page}」页面")
                else:
                    ui_control.goto_page(ui_page_dict[step.target_game_page], max_retry=2)
                self.log_to_gui(f"成功进入「{step.target_game_page}」页面")
                    
        except Exception as e:
            logger.error(f"执行步骤失败: {e}, step: {step}")

    @register_step(state_msg="执行宏操作")
    def execute_macro(self):
        if self.is_play_music:
            # 乐谱宏，检查当前是否在演奏界面
            if not page_play_music.is_current_page(itt):
                self.update_task_result(status=STATE_TYPE_FAILED, message="未进入演奏界面")
                return STEP_NAME_FINISH
        else:
            # 普通宏，检查分辨率
            aspect_ratio = self.macro_record.info.aspect_ratio
            _, width, height = HANDLE_OBJ.check_shape()
            if aspect_ratio == "16:9" and not (1.70<width/height<1.80):
                self.update_task_result(status=STATE_TYPE_FAILED, message=f"宏\"{self.macro_record.info.name}\"只支持16:9分辨率，请修改游戏设置")
                return STEP_NAME_FINISH
            elif aspect_ratio == "16:10" and not (1.55<width/height<1.65):
                self.update_task_result(status=STATE_TYPE_FAILED, message=f"宏\"{self.macro_record.info.name}\"只支持16:10分辨率，请修改游戏设置")
                return STEP_NAME_FINISH

        # 如果有延迟，先等待
        if self.delay > 0:
            time.sleep(self.delay)
        
        # 执行宏操作
        start_time = time.time()
        
        self._execute_range(self.macro_record.steps)

        execution_time = time.time() - start_time
        self.log_to_gui(f"宏执行结束！耗时: {execution_time:.2f}秒")
    
    def handle_finally(self):
        """清理资源"""
        for key in self.pressing_keys:
            itt.key_up(key)
        # 不调用父类的 handle_finally，因为不需要返回主界面

if __name__ == "__main__":
    task = RunMacroTask(session_id="debug", macro_filename="进出幻境刷怪宏")
    task.task_run()

