'''祝福闪光幻境'''
from whimbox.task.task_template import STATE_TYPE_FAILED, STEP_NAME_FINISH, TaskTemplate, register_step
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import *
from whimbox.common.cvars import DEBUG_MODE
from whimbox.config.config import global_config
from whimbox.common.keybind import keybind

class BlessTask(TaskTemplate):
    def __init__(self, session_id, level_name=None):
        super().__init__(session_id=session_id, name="bless_task")
        if not level_name:
            self.level_name = global_config.get("OneDragon", "bless_target")
        else:
            self.level_name = level_name
    

    @register_step("正在前往祝福闪光幻境")
    def step1(self):
        if self.level_name == '不做祝福闪光幻境':
            self.update_task_result(status=STATE_TYPE_FAILED, message="已设置不做祝福闪光幻境，跳过")
            return STEP_NAME_FINISH
        ui_control.goto_page(page_huanjing_bless)
    

    @register_step("选择试炼")
    def step2(self):
        self.log_to_gui(f"选择试炼：{self.level_name}")
        if not scroll_find_click(AreaBlessHuanjingLevelsSelect, self.level_name, str_match_mode=1):
            raise Exception(f"未找到{self.level_name}")
    
    @register_step("选择难度")
    def step3(self):
        if not wait_until_appear_then_click(TextBlessHuanjingDifficulty3):
            raise Exception("未找到困难难度选择按钮")
    
    @register_step("开始快速挑战")
    def step4(self):
        if not wait_until_appear_then_click(ButtonBlessHuanjingQuickPlay):
            raise Exception("未找到快速挑战按钮")
        time.sleep(0.5) #等待窗口弹出
        # 如果当前幻境就是默认消耗体力的幻境，就把次数调到最大
        default_energy_cost = global_config.get("OneDragon", "energy_cost")
        if default_energy_cost == "祝福闪光幻境":
            self.log_to_gui("已允许消耗所有活跃能量！")
            if not DEBUG_MODE:
                wait_until_appear_then_click(ButtonBlessHuanjingNumMax)
                time.sleep(0.2)
            else:
                self.log_to_gui("debug下，不消耗所有能量，为了能多测几次")
        if not wait_until_appear_then_click(ButtonHuanjingConfirm):
            self.log_to_gui("未找到注入能量按钮", is_error=True)
            wait_until_appear_then_click(ButtonHuanjingCancel)
            return "step6"


    @register_step("判断闪光是否已满")
    def step_check_full(self):
        itt.delay(0.5)
        itt.wait_until_stable()
        text_box_dict = itt.ocr_and_detect_posi(AreaBlessHuanjingFullWarning)
        logger.info(f"祝福闪光溢出OCR结果: {text_box_dict}")
        if "祝福闪光数量溢出" in text_box_dict:
            self.log_to_gui("祝福闪光数量溢出", is_error=True)
            AreaBlessHuanjingFullWarning.click(target_box=text_box_dict["取消"])
            self.update_task_result(
                status=STATE_TYPE_FAILED,
                message="祝福闪光数量溢出",
                data={"bless_sparkle_full": True},
            )
            wait_until_appear_then_click(ButtonHuanjingCancel)
            return "step6"


    @register_step("等待挑战完成")
    def step5(self):
        if skip_get_award():
            self.update_task_result(message="祝福闪光幻境完成")
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message="领取祝福闪光幻境奖励失败")
    

    @register_step("退出闪光幻境")
    def step6(self):
        ui_control.goto_page(page_main)


if __name__ == "__main__":
    bless_task = BlessTask(session_id="debug")
    bless_task.task_run()
        



