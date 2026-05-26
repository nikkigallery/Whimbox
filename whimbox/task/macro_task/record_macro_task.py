from whimbox.task.task_template import TaskTemplate, register_step
from whimbox.common.logger import logger
from whimbox.common.scripts_manager import *
from whimbox.common.utils.utils import save_json
from whimbox.common.path_lib import SCRIPT_PATH
from whimbox.common.handle_lib import HANDLE_OBJ

from pynput import keyboard, mouse
import time
import os

from whimbox.platform.factory import get_window_manager


class RecordMacroTask(TaskTemplate):
    """记录键鼠操作的任务"""
    
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="record_macro_task")
        self.steps = []
        
        # 录制状态
        self.is_recording = False
        self.last_event_time = None  # 上一个事件的时间
        
        # 键盘和鼠标监听器
        self.keyboard_listener = None
        self.mouse_listener = None
        
        # 按键状态跟踪，避免重复记录长按事件
        self.pressed_keys = set()  # 记录当前按下的键
        self.pressed_mouse_buttons = set()  # 记录当前按下的鼠标键
        
        # 窗口分辨率比例
        self.aspect_ratio = None
        
    def _screen_to_window_position(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        """将屏幕坐标转换为窗口内坐标（只对宽度归一化到1920）"""
        mgr = get_window_manager()
        handle = HANDLE_OBJ.get_handle()
        if not handle:
            logger.warning("无法获取窗口句柄，使用屏幕坐标")
            return (screen_x, screen_y)

        win_x, win_y, window_width, window_height = mgr.get_window_rect(
            handle, HANDLE_OBJ.pid
        )

        # 计算窗口内的相对坐标
        window_x = screen_x - win_x
        window_y = screen_y - win_y

        # 只对宽度归一化到 1920，高度保持原始比例
        if window_width > 0:
            normalized_x = int(window_x * 1920 / window_width)
            normalized_y = int(window_y * 1920 / window_width)
            return (normalized_x, normalized_y)
        else:
            return (window_x, window_y)
    
    def _on_keyboard_press(self, key):
        """键盘按下事件处理"""
        if not self.is_recording:
            return
            
        try:
            # 获取按键名称
            if hasattr(key, 'char') and key.char is not None:
                key_name = key.char
            elif hasattr(key, 'name'):
                key_name = key.name
            else:
                key_name = str(key)
            
            # 如果这个键已经被按下，忽略重复的 press 事件
            if key_name in self.pressed_keys:
                return
            
            current_time = time.time()
            
            # 如果不是第一个事件，添加间隔时间步骤
            if self.last_event_time is not None:
                gap_duration = current_time - self.last_event_time
                if gap_duration > 0.01:  # 大于10ms才记录间隔
                    gap_step = MacroStep(
                        type="gap",
                        duration=gap_duration
                    )
                    self.steps.append(gap_step)
            else:
                logger.info("检测到第一个事件，开始录制")
            
            # 更新最后事件时间
            self.last_event_time = current_time
            
            # 标记该键为已按下
            self.pressed_keys.add(key_name)
            
            step = MacroStep(
                type="keyboard",
                key=key_name,
                action="press"
            )
            
            self.steps.append(step)
            
        except Exception as e:
            logger.error(f"键盘按下记录错误: {e}")
    
    def _on_keyboard_release(self, key):
        """键盘松开事件处理"""
        if not self.is_recording:
            return
            
        try:
            # 获取按键名称
            if hasattr(key, 'char') and key.char is not None:
                key_name = key.char
            elif hasattr(key, 'name'):
                key_name = key.name
            else:
                key_name = str(key)
            
            # 从按下状态中移除该键
            self.pressed_keys.discard(key_name)
            
            current_time = time.time()
            
            # 如果不是第一个事件，添加间隔时间步骤
            if self.last_event_time is not None:
                gap_duration = current_time - self.last_event_time
                if gap_duration > 0.01:  # 大于10ms才记录间隔
                    gap_step = MacroStep(
                        type="gap",
                        duration=gap_duration
                    )
                    self.steps.append(gap_step)
            else:
                logger.info("检测到第一个事件，开始录制")
            
            # 更新最后事件时间
            self.last_event_time = current_time
            
            step = MacroStep(
                type="keyboard",
                key=key_name,
                action="release"
            )
            
            self.steps.append(step)
            
        except Exception as e:
            logger.error(f"键盘松开记录错误: {e}")
    
    def _on_mouse_click(self, x, y, button, pressed):
        """鼠标点击事件处理"""
        if not self.is_recording:
            return
            
        try:
            # 获取按键名称
            button_name = str(button).replace('Button.', '')
            button_name = f"mouse_{button_name}"
            
            # 防止重复记录鼠标按下事件
            if pressed:
                if button_name in self.pressed_mouse_buttons:
                    return
                self.pressed_mouse_buttons.add(button_name)
            else:
                self.pressed_mouse_buttons.discard(button_name)
            
            current_time = time.time()
            
            # 如果不是第一个事件，添加间隔时间步骤
            if self.last_event_time is not None:
                gap_duration = current_time - self.last_event_time
                if gap_duration > 0.01:  # 大于10ms才记录间隔
                    gap_step = MacroStep(
                        type="gap",
                        duration=gap_duration
                    )
                    self.steps.append(gap_step)
            else:
                logger.info("检测到第一个事件，开始录制")
            
            # 更新最后事件时间
            self.last_event_time = current_time
            
            # 转换为窗口内坐标
            window_pos = self._screen_to_window_position(x, y)
            
            step = MacroStep(
                type="mouse",
                key=button_name,
                action="press" if pressed else "release",
                position=window_pos
            )
            
            self.steps.append(step)
            
        except Exception as e:
            logger.error(f"鼠标点击记录错误: {e}")
    
    
    @register_step(state_msg="准备中，请稍等")
    def step1(self):
        """开始录制步骤"""
        # 初始化录制状态
        self.is_recording = True
        self.last_event_time = None  # 重置最后事件时间
        self.steps.clear()
        self.pressed_keys.clear()
        self.pressed_mouse_buttons.clear()
        
        # 检测窗口分辨率比例
        _, width, height = HANDLE_OBJ.check_shape()
        ratio = width / height
        if 1.70<ratio<1.80:
            self.aspect_ratio = "16:9"
        elif 1.55<ratio<1.65:
            self.aspect_ratio = "16:10"
        else:
            self.aspect_ratio = "其他"
        
        # 启动键盘监听器
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_keyboard_press,
            on_release=self._on_keyboard_release
        )
        self.keyboard_listener.daemon = True
        self.keyboard_listener.start()
        
        # 启动鼠标监听器（只监听点击事件，不监听移动）
        self.mouse_listener = mouse.Listener(
            on_click=self._on_mouse_click
        )
        self.mouse_listener.daemon = True
        self.mouse_listener.start()
        
        logger.info("开始录制宏")
        
    @register_step(state_msg="开始操作吧，不支持录制视角转动操作！")
    def step2(self):
        """等待录制完成"""
        # 持续等待直到停止录制
        while self.is_recording and not self.need_stop():
            time.sleep(0.1)
        
        # 停止监听器
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        
        # 检查是否有鼠标事件
        has_mouse_event = any(step.type == "mouse" for step in self.steps)
        aspect_ratio_to_save = self.aspect_ratio if has_mouse_event else None
        
        now = time.localtime(time.time())
        macro_name = f"我的宏_{time.strftime('%Y%m%d%H%M%S', now)}"
        macro_filename = f"{macro_name}.json"
        macro_info = MacroInfo(
            name=macro_name,
            type="宏",
            version="3.0",
            update_time=time.strftime("%Y-%m-%d %H:%M:%S", now),
            aspect_ratio=aspect_ratio_to_save
        )
        macro_record = MacroRecord(
            info=macro_info,
            steps=self.steps[:-2]
        )
        save_json(macro_record.model_dump(exclude_none=True), macro_filename, SCRIPT_PATH)
        # scripts_manager.init_scripts_dict()
        logger.info(f"宏保存成功，路径：{os.path.join(SCRIPT_PATH, macro_filename)}")
        self.update_task_result(message=f"录制成功，宏文件名：{macro_filename}", force_update=True)
    
    def task_stop(self):
        """手动停止录制"""
        super().task_stop()
        self.is_recording = False

    def handle_finally(self):
        """清理资源"""
        # 确保停止录制
        self.is_recording = False
        
        # 停止监听器
        if self.keyboard_listener and self.keyboard_listener.is_alive():
            self.keyboard_listener.stop()
        if self.mouse_listener and self.mouse_listener.is_alive():
            self.mouse_listener.stop()
        
        # 不调用父类的 handle_finally，因为不需要返回主界面
        pass

if __name__ == "__main__":
    task = RecordMacroTask(session_id="debug")
    task.task_run()

