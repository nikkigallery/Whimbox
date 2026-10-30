# 每周幻境

import json
import os

from whimbox.task.task_template import *
from whimbox.common.path_lib import ASSETS_PATH
from whimbox.ui.page_assets import page_daily_task, page_huanjing_weekly
from whimbox.ui.ui import ui_control
from whimbox.interaction.interaction_core import itt
from whimbox.ui.ui_assets import *
from whimbox.common.utils.ui_utils import *


def _load_realm_options():
    try:
        path = os.path.join(ASSETS_PATH, "setting_options.json")
        with open(path, "r", encoding="utf-8") as f:
            options = json.load(f).get("realm_target", [])
        return [item for item in options if item not in ("全部", "不做周本")]
    except Exception:
        return ["奇格格达", "卷卷"]


def _normalize_realm_targets(realm_target):
    all_targets = _load_realm_options()
    if isinstance(realm_target, list):
        return [item for item in realm_target if item in all_targets]
    if realm_target == "全部":
        return all_targets
    if realm_target == "不做周本" or not realm_target:
        return []
    return [realm_target] if realm_target in all_targets else []


class WeeklyRealmTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="weekly_realm_task")
        realm_target = global_config.get("OneDragon", "realm_target")
        self.realm_target = _normalize_realm_targets(realm_target)
        self.bless_sparkle_full = False

    @register_step("检查周本完成情况")
    def step1(self):
        if len(self.realm_target) == 0:
            self.update_task_result(status=STATE_TYPE_SUCCESS, message="已设置不做周本，跳过")
            return STEP_NAME_FINISH
        ui_control.goto_page(page_daily_task)
        weekly_count_str = itt.ocr_single_line(AreaWeeklyCountText)
        try:
            weekly_count_str = weekly_count_str.replace('v', '').replace('V', '').replace(' ', '')
            finished_count = int(weekly_count_str.split("/")[0])
            total_count = int(weekly_count_str.split("/")[1])
            self.log_to_gui(f"每周幻境完成情况: {finished_count}/{total_count}")
        except:
            raise Exception(f"每周幻境完成数量识别异常:{weekly_count_str}")
        if finished_count < total_count and finished_count < len(self.realm_target):
            return
        else:
            return "step4"
    
    @register_step("前往心之突破幻境")
    def step2(self):
        ui_control.goto_page(page_huanjing_weekly)
    
    def quick_challenge(self, level_name):
        self.log_to_gui(f"快速挑战{level_name}")
        if not scroll_find_click(AreaBlessHuanjingLevelsSelect, level_name, str_match_mode=1):
            self.log_to_gui(f"未找到{level_name}", is_error=True)
            return False
        if not wait_until_appear_then_click(ButtonBlessHuanjingQuickPlay):
            self.log_to_gui("未找到快速挑战按钮", is_error=True)
            return False
        else:
            itt.delay(0.5, comment="等待窗口弹出")
            if not wait_until_appear_then_click(ButtonHuanjingConfirm):
                self.log_to_gui("未找到注入能量按钮", is_error=True)
                wait_until_appear_then_click(ButtonHuanjingCancel)
                return False
            else:
                itt.delay(0.5)
                itt.wait_until_stable()
                self.log_to_gui("判断闪光是否已满")
                text_box_dict = itt.ocr_and_detect_posi(AreaBlessHuanjingFullWarning)
                logger.info(f"祝福闪光溢出OCR结果: {text_box_dict}")
                if "祝福闪光数量溢出" in text_box_dict:
                    self.bless_sparkle_full = True
                    self.log_to_gui("祝福闪光数量溢出", is_error=True)
                    self.update_task_result(
                        status=STATE_TYPE_FAILED,
                        message="祝福闪光数量溢出",
                        data={"bless_sparkle_full": True},
                    )
                    cancel_box = text_box_dict.get("取消")
                    if cancel_box is not None:
                        try:
                            AreaBlessHuanjingFullWarning.click(target_box=cancel_box)
                        except Exception as exc:
                            logger.warning(f"关闭祝福闪光溢出提示失败: {exc}")
                    else:
                        self.log_to_gui("未识别到溢出提示的取消按钮", is_error=True)
                    try:
                        wait_until_appear_then_click(ButtonHuanjingCancel)
                    except Exception as exc:
                        logger.warning(f"退出周本快速挑战失败: {exc}")
                    return False

        if skip_get_award():
            self.log_to_gui(f"{level_name}完成")
            return True
        else:
            raise Exception("领取奖励失败")

    @register_step("开始快速挑战每周幻境")
    def step3(self):
        for realm_name in self.realm_target:
            if self.need_stop():
                break
            if not self.quick_challenge(realm_name):
                if not self.bless_sparkle_full:
                    self.update_task_result(
                        status=STATE_TYPE_FAILED,
                        message=f"{realm_name}快速挑战失败",
                    )
                return STEP_NAME_FINISH

    @register_step("完成每周幻境")
    def step4(self):
        self.update_task_result(message="每周幻境已完成", data=True)

if __name__ == "__main__":
    task = WeeklyRealmTask(session_id="debug")
    task_result = task.task_run()
    print(task.task_result)


