from whimbox.common.utils.utils import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.img_utils import *
from whimbox.common.utils.posi_utils import *
from whimbox.common.logger import logger
from whimbox.ability.cvar import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.common.utils.ui_utils import *
from whimbox.config.config import global_config

import time


class AbilityManager:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AbilityManager, cls).__new__(cls)
        return cls._instance


    def __init__(self):
        if self._initialized:
            return

        self.current_ability = None
        self.ability_keymap = None
        self.jump_ability = None
        self.battle_ability = None
        self.is_shapeshifting = False
        self._initialized = True


    def reinit(self):
        # 每次自动跑图开始前，都应该再次初始化一遍，避免用户手动调整过能力
        self.current_ability = None
        self.ability_keymap = None
        self.jump_ability = None
        self.battle_ability = None
        self.is_shapeshifting = False

    def get_current_ability(self):
        cap = itt.capture(anchor_posi=AreaAbilityButton.position)
        lower_white = [0, 0, 230]
        upper_white = [180, 60, 255]
        img = process_with_hsv_limit(cap, lower_white, upper_white)
        for icon in ability_hsv_icons:
            resize_icon = cv2.resize(icon.image, None, fx=0.73, fy=0.73, interpolation=cv2.INTER_LINEAR)
            rate = similar_img(img, resize_icon[:, :, 0], ret_mode=IMG_RATE)
            if rate > 0.8:
                return icon_name_to_ability_name.get(icon.name, None)
        return None

    def check_current_ability(self, ability_icon:ImgIcon, cap=None):
        if cap is not None:
            cap = crop(cap, AreaAbilityButton.position)
        else:
            cap = itt.capture(anchor_posi=AreaAbilityButton.position)
        lower_white = [0, 0, 230]
        upper_white = [180, 60, 255]
        img = process_with_hsv_limit(cap, lower_white, upper_white)
        resize_icon = cv2.resize(ability_icon.image, None, fx=0.73, fy=0.73, interpolation=cv2.INTER_LINEAR)
        rate = similar_img(img, resize_icon[:, :, 0], ret_mode=IMG_RATE)
        if rate > 0.8:
            return True
        else:
            return False

    def _get_ability_hsv_icon(self, center, cap):
        area = area_offset((-ability_icon_radius, -ability_icon_radius, ability_icon_radius, ability_icon_radius), offset=center)
        area = AnchorPosi(area[0], area[1], area[2], area[3], anchor=ANCHOR_CENTER)
        img = crop(cap, area)
        lower_white = [0, 0, 230]
        upper_white = [180, 60, 255]
        img = process_with_hsv_limit(img, lower_white, upper_white)
        return img


    def _check_jump_ability(self):
        cap = itt.capture()
        img = self._get_ability_hsv_icon(jump_ability_center, cap)
        for icon in jump_ability_hsv_icons:
            rate = similar_img(img, icon.image[:, :, 0], ret_mode=IMG_RATE)
            if rate > 0.8:
                ability_name = icon_name_to_ability_name.get(icon.name, None)
                if ability_name is not None:
                    self.jump_ability = ability_name
                    return True
        logger.error(f'unknown jump ability icon')
        return False


    def _check_ability_keymap(self):
        ability_keymap = {}
        cap = itt.capture()
        for i, center in enumerate(ability_icon_centers):
            img = self._get_ability_hsv_icon(center, cap)
            for icon in ability_hsv_icons:
                rate = similar_img(img, icon.image[:, :, 0], ret_mode=IMG_RATE)
                if rate > 0.8:
                    logger.debug(f'{icon.name} rate: {rate}')
                    ability_name = icon_name_to_ability_name.get(icon.name, None)
                    if ability_name is None:
                        logger.error(f'unknown ability icon: {icon.name}')
                    else:
                        ability_keymap[ability_name] = i+1
                    break
        self.ability_keymap = ability_keymap
        return True


    def _change_ability_plan(self, ability_plan: int):
        # 切换能力配置方案，需要已经在能力配置界面
        AreaAbilityPlanChangeButton.click()
        time.sleep(0.2)
        if ability_plan == 1:
            AreaAbilityPlan1Button.click()
        elif ability_plan == 2:
            AreaAbilityPlan2Button.click()
        elif ability_plan == 3:
            AreaAbilityPlan3Button.click()
        else:
            raise(f'能力方案只能是123')
    

    def _set_ability(self, ability_name: str, ability_key):
        '''
        切换能力
        
        Args:
            ability_name: 能力名称，只能使用cvar中的ABILITY_NAME_XXX
            ability_key: 能力键位，只支持1~8和jump
        '''
        if self.ability_keymap.get(ability_name, None) == ability_key:
            return True

        target_ability_icon_center = ability_icon_centers[ability_key-1]
        itt.move_and_click(target_ability_icon_center, anchor=ANCHOR_CENTER)
        time.sleep(0.2)
        # 切换能力列表展示形式
        if itt.get_img_existence(ButtonAbilityConfig):
            pass
        else:
            texts = itt.ocr_multiple_lines(AreaAbilityChange)
            if len(texts) >= 8: # 根据列表区域的文字数量来判断当前是否已经是icon显示
                pass
            else:
                wait_until_appear_then_click(ButtonAbilityChangeList)
        # 向下滚动，寻找指定的ability_name
        res = scroll_find_click(AreaAbilityChange, ability_name)
        if res:
            self.ability_keymap[ability_name] = ability_key
        return res

    def get_ability_keybind(self, ability_index: str):
        if ability_index == 1:
            return keybind.KEYBIND_ABILITY_1
        elif ability_index == 2:
            return keybind.KEYBIND_ABILITY_2
        elif ability_index == 3:
            return keybind.KEYBIND_ABILITY_3
        elif ability_index == 4:
            return keybind.KEYBIND_ABILITY_4
        elif ability_index == 5:
            return keybind.KEYBIND_ABILITY_5
        elif ability_index == 6:
            return keybind.KEYBIND_ABILITY_6
        elif ability_index == 7:
            return keybind.KEYBIND_ABILITY_7
        elif ability_index == 8:
            return keybind.KEYBIND_ABILITY_8
        else:
            raise(f'ability_index can only 1~8, but got {ability_index}')

    def init_need_ability(self, ability_name_list):
        self.reinit()
        if ability_name_list is None or len(ability_name_list) == 0:
            return True, "当前路线不需要配置能力"
        
        if len(ability_name_list) > 8:
            raise(f'一条路线最多只允许使用8个能力')

        if len(ability_name_list) == 1:
            ability_name = ability_name_list[0]
            self.current_ability = self.get_current_ability()
            if self.current_ability == ability_name:
                return True, "当前能力已满足路线需求"

        ui_control.goto_page(page_ability)
        self._check_ability_keymap()
        is_satisfied = True
        for ability_name in ability_name_list:
            if not ability_name in self.ability_keymap:
                is_satisfied = False
                break
        if is_satisfied:
            ui_control.goto_page(page_main)
            return True, "当前能力轮盘已满足路线需求"
        else:
            self.ability_keymap = {}
            self.current_ability = None
            # 根据配置文件，配置到对应的方案
            ability_plan = global_config.get_int("OneDragon", "ability_plan")
            self._change_ability_plan(ability_plan)
            itt.wait_until_stable(threshold=0.99)
            # 检查当前能力键位
            self._check_ability_keymap()
            need_set_ability_name_list = []
            already_key_set = set()
            for ability_name in ability_name_list:
                if ability_name not in self.ability_keymap:
                    need_set_ability_name_list.append(ability_name)
                else:
                    already_key_set.add(self.ability_keymap[ability_name])
            # 剩余可配置能力的键位
            remain_key_set = set(range(1, 9))
            remain_key_list = list(remain_key_set - already_key_set)
            # 配置未配置的能力
            for need_set_ability_name in need_set_ability_name_list:
                self._set_ability(need_set_ability_name, remain_key_list.pop())
            # 点击保存按钮
            itt.appear_then_click(ButtonAbilitySave)
            ui_control.goto_page(page_main)
            return True, "配置能力轮盘成功"

    def change_ability(self, ability_name: str):
        ui_control.ensure_page(page_main)
        # 如果当前能力已经符合，就直接返回
        if self.current_ability == ability_name:
            return True
        # 否则根据能力轮盘进行切换
        key = None
        if self.ability_keymap:
            key = self.ability_keymap.get(ability_name, None)
        else:
            raise Exception('能力轮盘未初始化')
        if key:
            itt.key_press(self.get_ability_keybind(key))
            self.current_ability = ability_name
            itt.delay(0.5, comment="等待能力切换完成")
            return True
        else:
            raise Exception('切换能力失败')

    def check_subability_active(self):
        times = 3
        total_px_count = 0
        for i in range(times):
            cap = itt.capture(anchor_posi=AreaSubAbilityButton.position)
            lower = [0, 80, 200]
            upper = [30, 110, 255]
            px_count = count_px_with_hsv_limit(cap, lower, upper)
            total_px_count += px_count
            time.sleep(0.1)
        px_count = total_px_count / times
        # 只靠px_count不太能确定，最好通过技能开启前后的px_count变化来确定
        if px_count > 200:
            return True, px_count
        return False, px_count

ability_manager = AbilityManager()


if __name__ == "__main__":
    # CV_DEBUG_MODE = True
    ability_manager.init_need_ability([ABILITY_NAME_FISH, ABILITY_NAME_STAR_COLLECT, ABILITY_NAME_SHAPESHIFTING, ABILITY_NAME_INSECT])
    ability_manager.change_ability(ABILITY_NAME_SHAPESHIFTING)
    # print(ability_manager.get_current_ability())
    # ability_manager._check_jump_ability()
    # ability_manager._check_ability_keymap()
    # print(ability_manager.ability_keymap)
    # while True:
    #     print(ability_manager.check_subability_active())
    #     time.sleep(1)