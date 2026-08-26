import time
from enum import Enum
import re
import cv2

from whimbox.common.timer_module import AdvanceTimer
from whimbox.common.utils.ui_utils import skip_to_page_main, wait_until_appear
from whimbox.task.task_template import *
from whimbox.interaction.interaction_core import itt
from whimbox.ui.page_assets import page_main
from whimbox.ui.ui import ui_control
from whimbox.ui.ui_assets import *
from whimbox.common.utils.img_utils import count_px_with_hsv_limit, process_with_hsv_limit, similar_img
from whimbox.ability.ability import ability_manager
from whimbox.ability.cvar import ABILITY_NAME_FISH, ABILITY_NAME_RHYTHMS, ABILITY_NAME_STAR_COLLECT
from whimbox.common.logger import logger
from whimbox.common.keybind import keybind

hsv_limit = ([20, 50, 245], [30, 90, 255])

class FishingResult(Enum):
    SUCCESS = 0
    NO_FISH = 1
    WRONG_POSITION = 2

class FishingState(Enum):
    NOT_FISHING = 0
    FINISH = 1      # 收竿 (右键取消)
    STRIKE = 2      # 提竿 (S)
    PULL_LINE = 3   # 拉扯鱼线 (A/D)
    REEL_IN = 4     # 收线 (右键狂点)
    SKIP = 5        # 跳过 (F)
    UNKNOWN = 6

FISHING_STATE_MAPPING = [
    (IconFishingFinish, FishingState.FINISH),
    (IconFishingStrike, FishingState.STRIKE),
    (IconFishingPullLine, FishingState.PULL_LINE),
    (IconFishingPullLineHome, FishingState.PULL_LINE),
    (IconFishingReelIn, FishingState.REEL_IN),
    (IconSkip, FishingState.SKIP),
]

FISHING_TYPE_MIRALAND = "钓鱼"
FISHING_TYPE_HOME = "钓陨星"
_DEFAULT_MIRALAND_CAST_COUNT = 3
_DEFAULT_HOME_CAST_COUNT = 5


def _parse_cast_count(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        cast_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("钓鱼抛竿次数必须为正整数") from exc
    if cast_count <= 0:
        raise ValueError("钓鱼抛竿次数必须为正整数")
    return cast_count


class FishingTask(TaskTemplate):
    def __init__(
        self,
        session_id,
        fishing_type=None,
        already_material_count_dict=None,
        max_cast_count=None,
    ):
        super().__init__(session_id=session_id, name="fishing_task")
        self.fishing_type = fishing_type # 大世界钓鱼or家园钓星
        self.material_count_dict = {}
        self.already_material_count_dict = already_material_count_dict
        self.max_cast_count = _parse_cast_count(max_cast_count)

    def get_cast_count_limit(self):
        if self.max_cast_count is not None:
            return self.max_cast_count
        if self.fishing_type == FISHING_TYPE_HOME:
            return _DEFAULT_HOME_CAST_COUNT
        return _DEFAULT_MIRALAND_CAST_COUNT

    def get_fishing_type(self):
        cap = itt.capture(anchor_posi=AreaFishingIcons.position)
        if itt.get_img_existence(IconFishingHomeFeature, cap=cap):
            return FISHING_TYPE_HOME
        elif itt.get_img_existence(IconFishingMiralandFeature, cap=cap):
            return FISHING_TYPE_MIRALAND
        return FISHING_TYPE_MIRALAND

    def get_current_state(self):
        """在模板区域内检测当前状态"""
        cap = itt.capture(anchor_posi=AreaFishingIcons.position)
        for icon, state in FISHING_STATE_MAPPING:
            if itt.get_img_existence(icon, cap=cap):
                return state
        return FishingState.UNKNOWN

    def _pull_in_direction(self, key, px_count):
        """
        按下一个按键并检查方向是否正确。
        如果正确，则持续按住
        """
        itt.key_down(key)
        while not self.need_stop():
            time.sleep(0.2)
            cap = itt.capture(anchor_posi=AreaFishingDetection.position)
            current_px_count = count_px_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
            logger.debug(f"尝试方向: {key}, {px_count} -> {current_px_count}")
            if px_count - current_px_count > 5 or current_px_count == 0:
                px_count = current_px_count
                if px_count == 0:
                    break
                continue
            else:
                px_count = current_px_count
                break
        itt.key_up(key)
        return px_count

    def handle_pull_line(self):
        """处理拉扯鱼线状态的核心逻辑"""
        self.log_to_gui("进入拉扯鱼线状态")
        cap = itt.capture(anchor_posi=AreaFishingDetection.position)
        px_count = count_px_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
        while not self.need_stop():
            px_count = self._pull_in_direction('a', px_count)
            if self.get_current_state() != FishingState.PULL_LINE:
                break
            px_count = self._pull_in_direction('d', px_count)
            if self.get_current_state() != FishingState.PULL_LINE:
                break

    def handle_strike(self):
        self.log_to_gui("状态: 提竿")
        itt.key_press('s')

    def handle_reel_in(self):
        self.log_to_gui("状态: 收线")
        while not self.need_stop():
            start_time = time.time()
            itt.key_press(keybind.KEYBIND_FISHING_REEL_IN)
            cap = itt.capture(anchor_posi=AreaFishingIcons.position)
            if not itt.get_img_existence(IconFishingReelIn, cap=cap):
                break
            gap_time = time.time() - start_time
            if gap_time < 0.18:
                # 避免鼠标点击过快，导致吞鼠标事件
                time.sleep(0.18 - gap_time)

    def handle_skip(self):
        self.log_to_gui("状态: 跳过")
        # while not ui_control.verify_page(page_main):
        #     itt.key_press(keybind.KEYBIND_INTERACTION)
        #     time.sleep(0.2)
        skip_to_page_main()
        self.record_material()

    def record_material(self):
        # 从“笔刷鱼×1.6kg”文本中提取鱼名，并记录数量
        # 为了和其他采集任务统一，这里不记录重量，而是个数
        if self.fishing_type == FISHING_TYPE_HOME:
            self.log_to_gui(f"获得陨星")
            if "陨星" in self.material_count_dict:
                self.material_count_dict["陨星"] += 1
            else:
                self.material_count_dict["陨星"] = 1
        else:
            texts = itt.ocr_multiple_lines(AreaMaterialGetText)
            for line in texts:
                pattern = r"^(.+?)[×xX]([0-9]+(?:\.[0-9]+)?)kg$"
                match = re.match(pattern, line)
                if match:
                    fish_name = match.group(1)
                    self.log_to_gui(f"获得{fish_name}")
                    if fish_name in self.material_count_dict:
                        self.material_count_dict[fish_name] += 1
                    else:
                        self.material_count_dict[fish_name] = 1
                    break

    def check_subability(self):
        times = 3
        while times > 0 and not self.need_stop():
            cap = itt.capture(anchor_posi=AreaSubAbilityButton.position)
            lower_white = [0, 0, 230]
            upper_white = [180, 60, 255]
            img = process_with_hsv_limit(cap, lower_white, upper_white)
            resize_icon = cv2.resize(IconAbilityFish.image, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_LINEAR)
            rate = similar_img(img, resize_icon[:, :, 0], ret_mode=IMG_RATE)
            logger.info(f"钓星小技能图标相似度: {rate}")
            if rate > 0.8:
                return True
            times -= 1
            time.sleep(1)
        return False

    @register_step("切换钓鱼能力")
    def step1(self):
        if self.fishing_type == FISHING_TYPE_HOME:
            if self.already_material_count_dict:
                if "陨星" in self.already_material_count_dict:
                    self.update_task_result(status=STATE_TYPE_SUCCESS, message="之前已完成钓星，无需再钓")
                    return STEP_NAME_FINISH 
            if not ability_manager.change_ability(ABILITY_NAME_STAR_COLLECT):
                self.update_task_result(status=STATE_TYPE_FAILED, message="切换采星能力失败")
                return STEP_NAME_FINISH
            else:
                itt.right_click()
                itt.delay(2, comment="等待采星能力开启完毕")
                if not self.check_subability():
                    self.update_task_result(STATE_TYPE_SUCCESS, message="当前位置无法钓星")
                    itt.right_click()
                    return STEP_NAME_FINISH
                else:
                    self.material_count_dict["陨星"] = 0
        else:
            if global_config.get_bool("OneDragon", "start_rhythms"):
                self.log_to_gui("钓鱼前使用打窝套能力")
                if ability_manager.change_ability(ABILITY_NAME_RHYTHMS):
                    itt.right_click()
                    itt.delay(2, comment="等待进入打窝套能力动画")
                    wait_until_appear(IconPageMainFeature, area=None, retry_time=20)

            if not ability_manager.change_ability(ABILITY_NAME_FISH):
                self.update_task_result(status=STATE_TYPE_FAILED, message="切换钓鱼能力失败")
                return STEP_NAME_FINISH


    @register_step("开始钓鱼")
    def step2(self):
        cast_count = 0
        while not self.need_stop():
            if cast_count >= self.get_cast_count_limit():
                break
            cast_count += 1
            res = self.fishing_loop()
            itt.delay(0.5, comment="稍等一下再开始钓鱼，避免太快吞操作")
            if res == FishingResult.NO_FISH:
                break
            elif res == FishingResult.WRONG_POSITION:
                break
        
        if not self.need_stop():
            if len(self.material_count_dict) == 0:
                self.update_task_result(message="未钓到鱼")
            else:
                res = []
                for fish_name, fish_weight in self.material_count_dict.items():
                    res.append(f"{fish_name}x{fish_weight}")
                res_str = ", ".join(res)
                self.update_task_result(message=f"获得{res_str}", data=self.material_count_dict)
            
            if self.fishing_type == FISHING_TYPE_HOME:
                itt.delay(2, comment="等待钓星彻底结束")
                self.log_to_gui("结束采星能力")
                itt.right_click()

    def switch_fishing(self):
        if self.fishing_type == FISHING_TYPE_MIRALAND:
            itt.right_click()
        elif self.fishing_type == FISHING_TYPE_HOME:
            itt.key_press(keybind.KEYBIND_ABILITY_DERIVATION_1)
        else:
            itt.right_click()

    def fishing_loop(self):
        # 等待进入钓鱼状态
        is_started = False
        wrong_timer = AdvanceTimer(5) # 5秒没进入钓鱼状态，说明没甩进水里
        wrong_timer.start()
        while not self.need_stop():
            if wrong_timer.reached():
                return FishingResult.WRONG_POSITION
            current_state = self.get_current_state()
            if current_state != FishingState.FINISH:
                # 因为有可能被“后台任务-自动钓鱼”调用，已经抛竿进入等待状态，就不需要再右键了
                if not is_started:
                    is_started = True
                    self.switch_fishing()
                else:
                    time.sleep(0.5)
            else:
                break

        # 判断钓鱼类型
        if self.fishing_type is None:
            self.fishing_type = self.get_fishing_type()
        # 开始钓鱼
        logger.info("进入钓鱼状态")
        idle_timer = AdvanceTimer(30) # 30秒如果没有鱼，就说明钓鱼位置错了
        idle_timer.start()
        itt.delay(2, comment="等待弹出鱼钓光的提示框")
        if itt.get_img_existence(IconFishingNoFish):
            self.switch_fishing()
            while not ui_control.verify_page(page_main) and not self.need_stop():
                time.sleep(0.5)
            return FishingResult.NO_FISH
        
        unknown_state_count = 0
        strike_times = 0 
        while not self.need_stop():
            if idle_timer.started() and idle_timer.reached():
                self.switch_fishing()
                while not ui_control.verify_page(page_main) and not self.need_stop():
                    time.sleep(0.2)
                return FishingResult.WRONG_POSITION
    
            # 连续出现提竿状态的次数，正常应该一次loop中只出现一次
            # 家园钓星如果钓完了，还继续钓，就会出现连续多次提竿状态，可以作为结束的标志
            state = self.get_current_state()
            logger.debug(f"当前状态: {state}")
            if state != FishingState.UNKNOWN:
                unknown_state_count = 0
                if state in [FishingState.NOT_FISHING, FishingState.FINISH]:
                    time.sleep(0.5)
                    continue
                elif state == FishingState.STRIKE:
                    if strike_times > 3:
                        return FishingResult.NO_FISH
                    idle_timer.clear()
                    self.handle_strike()
                    strike_times += 1
                    continue
                elif state == FishingState.PULL_LINE:
                    self.handle_pull_line()
                    continue
                elif state == FishingState.REEL_IN:
                    self.handle_reel_in()
                    continue
                elif state == FishingState.SKIP:
                    self.handle_skip()
                    break
            else:
                # 有可能因为状态切换的中间帧，导致识别失败
                # 所以连续3次判断为UNKNOWN，才认为是结束了
                unknown_state_count += 1
                logger.debug(f"连续{unknown_state_count}次识别为UNKNOWN")
                if unknown_state_count > 4:
                    self.handle_skip()
                    break
                else:
                    time.sleep(0.1)

        return FishingResult.SUCCESS

    def handle_finally(self):
        pass


if __name__ == "__main__":
    ability_manager.init_need_ability([ABILITY_NAME_FISH])
    # # CV_DEBUG_MODE = True
    # task = FishingTask(session_id="debug", fishing_type=FISHING_TYPE_HOME)
    task = FishingTask(session_id="debug", fishing_type=FISHING_TYPE_MIRALAND)
    task.task_run()
    # from whimbox.common.utils.img_utils import IMG_RATE
    # while True:
    #     time.sleep(1)
    #     print(task.get_fishing_type())

