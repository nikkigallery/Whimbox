from whimbox.task.task_template import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.ui.ui_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.logger import logger

class EnterGameTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="enter_game_task")

    @register_step("进入游戏")
    def step_enter_game(self):
        while not self.need_stop():
            text_box_dict = itt.ocr_and_detect_posi(AreaLoginOCR)
            if "点击进入游戏" in text_box_dict:
                AreaLoginOCR.click(target_box=text_box_dict["点击进入游戏"])
                break
         # 不停点击，直到进入loading界面
        while not self.need_stop():
            time.sleep(1)
            itt.move_and_click((100, 100))
            if itt.get_img_existence(IconUILoading):
                break
        
    @register_step("加载游戏中……")
    def step_loading_game(self):
        while not self.need_stop():
            time.sleep(1)
            if not itt.get_img_existence(IconUILoading):
                self.log_to_gui("游戏加载完成")
                break
        # 不停点击，尝试点掉月卡界面，直到出现主界面
        self.log_to_gui("检测是否需要领取小月卡")
        times = 0
        while not self.need_stop():
            time.sleep(1)
            # 有些电脑比较卡，会在小月卡出现前卡出主界面特征，所以需要多次验证
            if itt.get_img_existence(IconPageMainFeature):
                times += 1
                if times > 3:
                    self.update_task_result(status=STATE_TYPE_SUCCESS, message="成功进入游戏")
                    break
            else:
                itt.key_press(keybind.KEYBIND_INTERACTION)
    
    def handle_finally(self):
        pass
    
if __name__ == "__main__":
    task = EnterGameTask(session_id="debug")
    result = task.task_run()
    print(result)