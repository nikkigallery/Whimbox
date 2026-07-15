from whimbox.task.task_template import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.ui.ui_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.logger import logger
from whimbox.common.utils.ui_utils import scroll_find_click, wait_until_appear_then_click
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

    def _normalize_account_key(self, account):
        account = str(account)
        if not account.isascii():
            return ""
        allowed_chars = "abcdefghijklmnopqrstuvwxyz0123456789@."
        return "".join(
            char for char in account.lower()
            if char in allowed_chars
        )

    def get_account_box_dict(self, cap=None, show_res=False, y_threshold=10):
        text_box_dict = itt.ocr_and_detect_posi(AreaLoginAccountList, cap=cap, show_res=show_res)
        if not text_box_dict:
            return {}

        logger.info(f"账号列表OCR结果: {text_box_dict}")

        text_boxes = []
        for text, box in text_box_dict.items():
            x1, y1, x2, y2 = [float(v) for v in box]
            text_boxes.append({
                "text": text,
                "box": [x1, y1, x2, y2],
                "x1": x1,
                "y1": y1,
            })

        lines = []
        for item in sorted(text_boxes, key=lambda item: item["y1"]):
            for line in lines:
                if abs(item["y1"] - line["y1"]) <= y_threshold:
                    line["items"].append(item)
                    line["y1"] = min(i["y1"] for i in line["items"])
                    break
            else:
                lines.append({"y1": item["y1"], "items": [item]})

        account_box_dict = {}
        for line in lines:
            items = sorted(line["items"], key=lambda item: item["x1"])
            account = "".join(item["text"] for item in items).strip()
            account = self._normalize_account_key(account)
            if not account:
                continue

            x1 = min(item["box"][0] for item in items)
            y1 = min(item["box"][1] for item in items)
            x2 = max(item["box"][2] for item in items)
            y2 = max(item["box"][3] for item in items)
            account_box_dict[account] = [x1, y1, x2, y2]

        logger.info(f"账号列表OCR合并结果: {account_box_dict}")
        return account_box_dict

    @register_step("退出登录")
    def step_logout(self):
        itt.delay(3, comment="等待进入登录界面")
        # 如果当前已经是退出登录状态，直接去下一步
        if itt.get_img_existence(ButtonLogin):
            return
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
                account_box_dict = self.get_account_box_dict()
                for key, _ in self._iter_text_box_by_y(account_box_dict):
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
            logger.info(f"账号列表: {self.account_list}")
        
        logger.info(f"已完成账号列表：{self.finished_account_list}")
        if len(self.finished_account_list) == 0:
            scroll_find_click(AreaLoginOCR, "登录", need_scroll=False)
            self.current_account = self.account_list[0]
        else:
            self.current_account = ""
            cap = itt.capture(anchor_posi = AreaLoginAccountList.position)
            while not self.need_stop():
                account_box_dict = self.get_account_box_dict()
                for key, box in account_box_dict.items():
                    if key not in self.account_list:
                        self.account_list.append(key)
                    if key not in self.finished_account_list:
                        AreaLoginAccountList.click(target_box=box)
                        time.sleep(0.5)
                        scroll_find_click(AreaLoginOCR, "登录", need_scroll=False)
                        self.current_account = key
                        break
                if self.current_account:
                    break
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

        logger.info(f"当前账号: {self.current_account}")
        self.log_to_gui("账号切换完毕，开始进入游戏")
        task_result = EnterGameTask(session_id=self.session_id).task_run()
        if task_result.status == STATE_TYPE_SUCCESS:
            self.update_task_result(status=STATE_TYPE_SUCCESS, message="切换账号成功", data={"current_account": self.current_account})
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message="切换账号失败")
    
    def handle_finally(self):
        pass
        
        

if __name__ == "__main__":
    account_list=[]
    finished_account_list=[]
    task = ChangeAccountTask(session_id="debug", account_list=account_list, finished_account_list=finished_account_list)
    task.task_run()
    print(account_list, finished_account_list)

    # import cv2, os
    # from whimbox.common.path_lib import ROOT_PATH
    # cap = cv2.imread(os.path.join(ROOT_PATH, "..", "tools", "snapshot", "bug", "55.png"))
    # task.get_account_box_dict(cap=cap, show_res=True)
