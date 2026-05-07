from whimbox.task.task_template import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.ui.ui_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.logger import logger
from whimbox.common.utils.ui_utils import wait_until_appear_then_click
from whimbox.common.utils.img_utils import similar_img
from whimbox.task.common_task.enter_game_task import EnterGameTask

class ChangeAccountTask(TaskTemplate):
    def __init__(self, session_id, account_list=None, finished_account_list=None):
        super().__init__(session_id=session_id, name="change_account_task")
        self.account_list = account_list
        self.finished_account_list = finished_account_list
        self.current_account = ""

    def _iter_text_box_by_y(self, text_box_dict):
        return sorted(text_box_dict.items(), key=lambda item: item[1][1])

    @register_step("退出登录")
    def step_logout(self):
        itt.delay(3, comment="等待进入登录界面")
        if wait_until_appear_then_click(ButtonExitLogout, retry_time=20):
            while not self.need_stop():
                itt.delay(1)
                text_box_dict = itt.ocr_and_detect_posi(AreaLoginOCR)
                logger.info(f"登录界面文字: {text_box_dict.keys()}")
                if "确认" in text_box_dict:
                    self.log_to_gui("有确认按钮我直接点！")
                    AreaLoginOCR.click(target_box=text_box_dict["确认"])
                elif "同意" in text_box_dict:
                    self.log_to_gui("有同意按钮我直接点！")
                    AreaLoginOCR.click(target_box=text_box_dict["同意"])
                if itt.get_img_existence(ButtonLogin):
                    return
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message="没有找到退出登录按钮")
            return STEP_NAME_FINISH

    @register_step("切换账号登录")
    def step_change_account(self):
        if not wait_until_appear_then_click(ButtonLogin):
            self.update_task_result(status=STATE_TYPE_FAILED, message="没有找到登录按钮")
            return STEP_NAME_FINISH

        itt.delay(0.5, comment="等待账号列表出现")
        if len(self.account_list) == 0:
            self.log_to_gui("开始获取账号列表")
            cap = itt.capture(anchor_posi = AreaLoginAccountList.position)
            while not self.need_stop():
                text_box_dict = itt.ocr_and_detect_posi(AreaLoginAccountList)
                for key, _ in self._iter_text_box_by_y(text_box_dict):
                    if '****' in key:
                        if key not in self.account_list:
                            self.account_list.append(key)
                scroll_posi = (AreaLoginAccountList.position.x2, AreaLoginAccountList.position.y2)
                itt.move_to(scroll_posi, anchor=AreaLoginAccountList.position.anchor)
                itt.middle_scroll(-15)
                time.sleep(0.2)
                # 如果画面不再变化，说明滚到底了
                new_cap = itt.capture(anchor_posi = AreaLoginAccountList.position)
                rate = similar_img(cap, new_cap)
                if rate > 0.99:
                    break
                else:
                    cap = new_cap
        if len(self.finished_account_list) == 0:
            wait_until_appear_then_click(TextLoginAccountLoginButton)
            self.current_account = self.account_list[0]
        else:
            cap = itt.capture(anchor_posi = AreaLoginAccountList.position)
            while not self.need_stop():
                text_box_dict = itt.ocr_and_detect_posi(AreaLoginAccountList)
                for key in text_box_dict.keys():
                    if '****' in key:
                        if key not in self.finished_account_list:
                            AreaLoginAccountList.click(target_box=text_box_dict[key])
                            time.sleep(0.5)
                            wait_until_appear_then_click(TextLoginAccountLoginButton)
                            self.current_account = key
                scroll_posi = (AreaLoginAccountList.position.x2, AreaLoginAccountList.position.y2)
                itt.move_to(scroll_posi, anchor=AreaLoginAccountList.position.anchor)
                itt.middle_scroll(-15)
                time.sleep(0.2)
                # 如果画面不再变化，说明滚到底了
                new_cap = itt.capture(anchor_posi = AreaLoginAccountList.position)
                rate = similar_img(cap, new_cap)
                if rate > 0.99:
                    break
                else:
                    cap = new_cap

        self.log_to_gui("账号切换完毕，开始进入游戏")
        task_result = EnterGameTask(session_id=self.session_id).task_run()
        if task_result.status == STATE_TYPE_SUCCESS:
            self.update_task_result(status=STATE_TYPE_SUCCESS, message="切换账号成功", data={"current_account": self.current_account})
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message="切换账号失败")
    
    def handle_finally(self):
        pass
        
        

if __name__ == "__main__":
    start_game_task = ChangeAccountTask(session_id="debug", account_list=[])
    start_game_task.task_run()
