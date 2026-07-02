'''奇迹之冠'''
from whimbox.common.utils.ui_utils import *
from whimbox.task.task_template import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.ui.ui_assets import *
from whimbox.interaction.interaction_core import itt

import time

class MiraCrownTask(TaskTemplate):
    def __init__(self, session_id, force_start=False):
        super().__init__(session_id=session_id, name="mira_crown_task")
        self.force_start = force_start
        self.is_quick_reward = False
    
    @register_step("检查奇迹之冠巅峰赛进度")
    def step1(self):
        ui_control.goto_page(page_daily_task)
        text = itt.ocr_single_line(AreaMiraCrownOverview)
        count_str = text.replace('v', '').replace('V', '').replace(' ', '')
        try:
            finished_count = int(count_str.split("/")[0])
            total_count = int(count_str.split("/")[1])
        except:
            raise Exception(f"检查奇迹之冠巅峰赛进度识别异常:{count_str}")
        self.log_to_gui(f"奇迹之冠巅峰赛进度为{finished_count}/{total_count}")
        if finished_count != 0 and not self.force_start:
            self.update_task_result(message=f"奇迹之冠巅峰赛已做过，直接跳过")
            return STEP_NAME_FINISH
        else:
            return

    @register_step("进入奇迹之冠巅峰赛")
    def step2(self):
        AreaMiraCrownOverview.click()
        itt.wait_until_stable(0.95)
        AreaMiraCrownEntrance.click()
        itt.wait_until_stable(0.95)
        wait_until_appear_then_click(ButtonMiraCrownRank, retry_time=1)
        itt.delay(2, comment="等待巅峰赛跳关结束")
        if wait_until_appear_then_click(ButtonMiraCrownQuickReward):
            itt.delay(5, comment="等待奖励弹出")
            skip_get_award()
            self.is_quick_reward = True
    
    @register_step("进入挑战")
    def step3(self):            
        # 如果是快速奖励进来的，要从第二个门进去（第三个门是锁住的），不然从第三个门进去
        if not self.is_quick_reward:
            AreaMiraCrownThirdDoor.click()
        else:
            AreaMiraCrownSecondDoor.click()
        itt.wait_until_stable(0.95)
        itt.move_to((0, 0)) # 移走鼠标，避免触发某些ui的悬停效果，影响识别
        if wait_until_appear_then_click(ButtonMiraCrownStartChallenge):
            itt.wait_until_stable(threshold=0.95)
            ui_control.ui_additional()
            if not wait_until_appear(IconPageMainFeature, retry_time=10):
                raise Exception("未进入奇迹之冠巅峰赛内部")
        else:
            self.update_task_result(message="之前已经全都挑战完了")
            return STEP_NAME_FINISH
        retry_time = 3
        while not self.need_stop() and retry_time > 0:
            itt.key_down(keybind.KEYBIND_FORWARD)
            time.sleep(0.8)
            itt.key_up(keybind.KEYBIND_FORWARD)
            time.sleep(0.2) # 等待弹出按钮
            if wait_until_appear(IconTalkFeature, area=AreaPickup):
                itt.key_press(keybind.KEYBIND_INTERACTION)
                return
            retry_time -= 1
        if retry_time == 0:
            raise Exception("未找到对话按钮")
        
    
    @register_step("开始挑战")
    def step4(self):
        skip_dialog()
        itt.delay(0.5, comment="等待对话选项弹出")
        if not scroll_find_click(AreaDialogSelection, "继续挑战", need_scroll=False):
            if not scroll_find_click(AreaDialogSelection, "开始挑战", need_scroll=False):
                return "step6"
        skip_dialog()
        return
        
    @register_step("使用推荐搭配")
    def step5(self):
        wait_until_appear(ButtonMiraCrownNextStep)
        itt.delay(1, "等待界面加载完全")
        if not scroll_find_click(AreaMiraCrownAutoMatchButton, "推荐搭配", need_scroll=False):
            raise Exception("未找到推荐搭配按钮")
        itt.delay(2, comment="搭配完会卡一下")
        if not wait_until_appear_then_click(ButtonMiraCrownNextStep):
            raise Exception("未找到下一步按钮")
        if not wait_until_appear_then_click(ButtonMiraCrownConfirmMatch):
            raise Exception("未找到确认搭配按钮")
        wait_time = 20
        while not self.need_stop() and wait_time > 0:
            if itt.get_img_existence(ButtonMiraCrownSkipAll):
                ButtonMiraCrownSkipAll.click()
            if itt.get_img_existence(IconClickSkip):
                itt.key_press(keybind.KEYBIND_INTERACTION)
                break
            time.sleep(1)
            wait_time -= 1
        if wait_time == 0:
            # 等了20秒，怎么也应该结束了
            itt.key_press(keybind.KEYBIND_INTERACTION)
        itt.delay(2, comment="等待从挑战中退出来")
        skip_get_award()
        # 打完最后一关，会退出到主界面，否则会继续进入对话
        if itt.get_img_existence(IconPageMainFeature):
            return
        else:
            return "step4"
    
    @register_step("领取奖励")
    def step6(self):
        if not global_config.get_bool("OneDragon", "get_mira_crown_award", False):
            self.log_to_gui("未设置自动领取巅峰赛奖励，跳过")
            return STEP_NAME_FINISH
        
        ui_control.goto_page(page_esc)
        if not scroll_find_click(AreaEscEntrances, "奇迹之冠"):
            raise Exception("奇迹之冠入口未找到")
        itt.wait_until_stable(0.95)
        AreaMiraCrownEntrance.click()
        itt.wait_until_stable(0.95)
        wait_until_appear_then_click(ButtonMiraCrownRank, retry_time=1)
        
        # 领取奖励
        if not wait_until_appear_then_click(ButtonMiraCrownAward):
            raise Exception("未找到奇迹之冠“赛事嘉奖”按钮")
        itt.delay(1, comment="等待奖励界面弹出")
        if not wait_until_appear_then_click(ButtonMiraCrownRewardGet):
            self.log_to_gui("当前暂无奖励可领取", is_error=True)
        else:
            skip_get_award()
        itt.key_press("esc")
        
        # 兑换
        if not wait_until_appear_then_click(ButtonMiraCrownShop):
            raise Exception("未找到奇迹之冠“晶石兑换”按钮")
        itt.delay(1, comment="等待兑换界面弹出")
        targets = global_config.get("OneDragon", "mira_crown_award_target")
        for target in targets:
            if not scroll_find_click(AreaMiraCrownShopItemList, target, str_match_mode=1, need_scroll=False):
                raise Exception("未找到“" + target + "”的兑换按钮")
            else:
                if not wait_until_appear(ButtonMiraCrownShopMax):
                    self.log_to_gui(f"“{target}”已被兑换完，无需再次兑换")
                    continue
                if DEBUG_MODE:
                    self.log_to_gui("debug下，不点max按钮，为了能多测几次")
                else:
                    if not wait_until_appear_then_click(ButtonMiraCrownShopMax):
                        raise Exception("未找到最大化按钮")
                if not wait_until_appear_then_click(ButtonMiraCrownShopConfirm):
                    raise Exception("未找到确认按钮")
                skip_get_award()
                self.log_to_gui(f"成功兑换“{target}”")
                itt.delay(0.5, comment="等待兑换完成")
    
    @register_step("挑战结束")
    def step7(self):
        back_to_page_main()
                

if __name__ == "__main__":
    task = MiraCrownTask(session_id="debug", force_start=True)
    result = task.task_run()
    print(result.to_dict())
    # task.step6()

