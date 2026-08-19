from whimbox.common import timer_module
from whimbox.map.detection.cvars import MOVE_SPEED
from whimbox.ui.ui import ui_control
from whimbox.ui.ui_assets import *
from whimbox.ui.page_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.map.data.nikki_teleporter import DICT_TELEPORTER
from whimbox.map.detection.bigmap import BigMap
from whimbox.map.detection.minimap import MiniMap
from whimbox.map.detection.utils import trans_region_name_to_map_name
from whimbox.map.convert import *
from whimbox.common.logger import logger
from whimbox.common.utils.posi_utils import *
from whimbox.common.errors import BigMapTPError
from whimbox.common.utils.ui_utils import *
from whimbox.common.cvars import get_current_stop_flag

import threading
import time
import typing as t


class Map(MiniMap, BigMap):

    def __init__(self):
        MiniMap.__init__(self)
        BigMap.__init__(self)

        # Set bigmap tp arguments
        self.MAP_POSI2MOVE_POSI_RATE = 0.6  # 移动距离与力度的比例
        self.BIGMAP_TP_OFFSET = 20  # 距离目标小于该误差则停止
        self.BIGMAP_MOVE_MAX = 300  # 最大移动力度
        self.TP_RANGE = 200  # 在该像素范围内可tp
        self.MINIMAP_UPDATE_LIMIT = 0.1  # minimap更新最短时间
        self.MINIMAP_ERROR_BASE_LIMIT = 20  # minimap基本更新误差

        self.smallmap_upd_timer = timer_module.Timer(10)
        self.small_map_init_flag = False
        self.lock = threading.Lock()
        self.check_bigmap_timer = timer_module.Timer(5)
        self.last_valid_position = [0, 0]
        self.history_position_list = []
        self.region_name = None
        self.map_name = None
        

    def _upd_smallmap(self) -> None:
        if itt.get_img_existence(IconPageMainFeature):
            self.update_position(itt.capture())


    def _is_reset_position(self, curr_posi, threshold=0.8):
        """如果历史点位种有threshold％偏移超过150px，则返回True。

        Args:
            curr_posi (_type_): _description_
            threshold (float, optional): _description_. Defaults to 0.8.

        Returns:
            _type_: _description_
        """
        if len(self.history_position_list) >= 20:
            over_times = 0
            for i in self.history_position_list:
                if euclidean_distance(i, curr_posi) >= 150:
                    over_times += 1
            return over_times / 20 > threshold
        return False

    def get_position(self, is_verify_position=False, use_cache = False):
        """get current character position

        Returns:
            list: px format
        """
        if use_cache:
            return self.position

        if not self.small_map_init_flag:
            self.reinit_smallmap()
            ui_control.ensure_page(page_main)
            self.small_map_init_flag = True
            
        self._upd_smallmap()
        self.history_position_list.append(self.position)
        # 由于minimap的update_position方法种已经有校验了，所以这里一般不校验
        if is_verify_position:
            if self._is_reset_position(self.position):
                self.history_position_list = []
            else:
                last_dist = euclidean_distance(self.last_valid_position, self.position)
                error_limit = self.MINIMAP_ERROR_BASE_LIMIT + self.smallmap_upd_timer.get_diff_time() * MOVE_SPEED
                if last_dist > error_limit:
                    logger.warning(
                        f"migration of position {round(last_dist, 2)} over limit {round(error_limit, 2)}, give up position")
                    self.minimap_print_log()
                    return self.last_valid_position

        self.smallmap_upd_timer.reset()
        r_posi = self.position
        self.last_valid_position = r_posi
        if len(self.history_position_list) > 20:
            self.history_position_list.pop(0)
        return list(r_posi)
        

    def update_region_and_map_name(self, use_cache=False) -> str:
        if use_cache and self.region_name is not None and self.map_name is not None:
            return self.region_name, self.map_name
        else:
            hsv_lower = [0, 0, 0]
            hsv_upper = [180, 255, 180] # hsv阈值处理，排除地图背景图案和文字的干扰
            self.region_name = itt.ocr_single_line(AreaBigMapRegionName, padding=50, hsv_limit=(hsv_lower, hsv_upper))
            self.map_name = trans_region_name_to_map_name(self.region_name)
            if self.map_name == MAP_NAME_HOME:
                self.region_name = REGION_NAME_HOME
            return self.region_name, self.map_name


    def reinit_smallmap(self) -> None:
        ui_control.goto_page(page_bigmap)
        self.update_region_and_map_name()
        if self.map_name == MAP_NAME_UNSUPPORTED:
            self.init_position((0, 0))
            self.small_map_init_flag = True
            self.last_valid_position = self.position
            self.smallmap_upd_timer.reset()
            return False
        else:
            posi = self.get_bigmap_posi()
            self.init_position(tuple(map(int, list(posi))))
            # ui_control.goto_page(page_main)
            self.small_map_init_flag = True
            self.last_valid_position = self.position
            self.smallmap_upd_timer.reset()
            return True

    def get_direction(self) -> float:
        self.update_direction(itt.capture())
        return self.direction

    def get_rotation(self) -> float:
        pt = time.time()
        self.update_rotation(itt.capture())
        if time.time() - pt > 0.1:
            logger.info(f"get_rotation spent too long: {time.time() - pt}")
        return self.rotation

    def maximize_bigmap_scale(self) -> None:
        # todo：原地tp，会导致ButtonBigMapZoom被弹出的传送菜单遮挡，无法继续
        ui_control.ensure_page(page_bigmap)
        times = 3
        while times > 0 and not itt.get_img_existence(IconBigMapMaxScale):
            itt.appear_then_click(ButtonBigMapZoom)
            time.sleep(0.5)
            times -= 1

    def get_bigmap_posi(self, is_upd=True, is_log=False) -> t.Tuple[float, float]:
        self.maximize_bigmap_scale()
        if is_upd:
            self.update_bigmap(itt.capture())
        if is_log:
            logger.debug(f"bigmap px posi: {self.bigmap_position}")
        return self.bigmap_position

    def _move_bigmap(self, target_posi, force_center=False) -> list:
        """move bigmap center to target position

        Args:
            target_posi (_type_): png map上的目标坐标
        
        警告：此函数为内部函数，不要在外部调用。如果一定要调用应先设置地图缩放。
        
        """
        screen_center_x = 1920 / 2
        screen_center_y = 1080 / 2

        stop_flag = get_current_stop_flag()
        if stop_flag.is_set():
            return list([screen_center_x, screen_center_y])

        itt.move_to([screen_center_x, screen_center_y], anchor=ANCHOR_CENTER)  # screen center
        itt.left_down()

        curr_posi = self.get_bigmap_posi()
        dx = min((curr_posi[0] - target_posi[0]) * self.MAP_POSI2MOVE_POSI_RATE, self.BIGMAP_MOVE_MAX)
        dx = max(dx, -self.BIGMAP_MOVE_MAX)
        dy = min((curr_posi[1] - target_posi[1]) * self.MAP_POSI2MOVE_POSI_RATE, self.BIGMAP_MOVE_MAX)
        dy = max(dy, -self.BIGMAP_MOVE_MAX)

        logger.debug(f"curr: {curr_posi} target: {target_posi}")
        logger.debug(f"_move_bigmap: {dx} {dy}")

        itt.move_to([dx, dy], relative=True, smooth=True)
        itt.delay(0.2, comment="waiting bigmap move")
        itt.left_up()

        after_move_posi = self.get_bigmap_posi()
        if not force_center:
            if euclidean_distance(
                convert_PngMapPx_to_InGameMapPx(after_move_posi, self.map_name), 
                convert_PngMapPx_to_InGameMapPx(target_posi, self.map_name)
                ) <= self.TP_RANGE:
                return list(
                    convert_PngMapPx_to_InGameMapPx(target_posi, self.map_name)
                    - convert_PngMapPx_to_InGameMapPx(after_move_posi, self.map_name)
                    + np.array([screen_center_x, screen_center_y]))

        if euclidean_distance(after_move_posi, target_posi) <= self.BIGMAP_TP_OFFSET:
            return list([screen_center_x, screen_center_y])  # screen center
        else:
            # if euclidean_distance(after_move_posi, curr_posi) <= self.BIGMAP_TP_OFFSET:
            #     return self._move_bigmap(target_posi=target_posi, float_posi=float_posi + 45)
            # else:
            #     return self._move_bigmap(target_posi=target_posi)
            stop_flag = get_current_stop_flag()
            if stop_flag.is_set():
                return list(
                    convert_PngMapPx_to_InGameMapPx(target_posi, self.map_name)
                    - convert_PngMapPx_to_InGameMapPx(after_move_posi, self.map_name)
                    + np.array([screen_center_x, screen_center_y]))
            return self._move_bigmap(target_posi=target_posi)

    def find_closest_teleporter(self, posi: list, map_name: str):
        """
        return closest teleporter position: 
        
        input:  png map position;
        return: png map position.
        """
        min_dist = 99999
        min_teleporter = None
        for checkpoint in DICT_TELEPORTER[map_name]:
            cp_posi = checkpoint.position
            dist = euclidean_distance(posi, cp_posi)
            if dist < min_dist:
                min_teleporter = checkpoint
                min_dist = dist
        return min_teleporter

    def _switch_to_area(self, tp_province, tp_region):

        def expand_province_dropdown(tp_province, first_region, text_box_dict):
            # 如果识别出“纪念山地”，说明心愿原野下拉框已展开
            if not first_region in text_box_dict:
                box = text_box_dict[tp_province]
                AreaBigMapRegionSelect.click(target_box=box)
                time.sleep(0.5)

        # 判断当前区域是否是目标区域
        if tp_region == REGION_NAME_HOME:
            # 如果目标区域是家园，则特殊处理，因为家园的名字不是固定的，使用图标进行判断
            AreaBigMapRegionName.click()
            time.sleep(0.5)
            if scroll_find_click(AreaBigMapRegionSelect, IconBigMapHomeFeature, threshold=IconBigMapHomeFeature.threshold):
                self.region_name = REGION_NAME_HOME
                self.map_name = MAP_NAME_HOME
                itt.wait_until_stable()
                wait_until_appear(IconUIBigmap)
                return True
            else:
                return False
        else:
            current_region, _ = self.update_region_and_map_name()
            if current_region != tp_region:
                # 不是目标区域，就进行区域选择
                AreaBigMapRegionName.click()
                time.sleep(0.5)
                text_box_dict = itt.ocr_and_detect_posi(AreaBigMapRegionSelect)
                if tp_province not in text_box_dict or tp_province in ["星海"]:
                    # 如果目标province不在当前页面，说明当前province不是目标，就滑动并点击展开
                    if not scroll_find_click(AreaBigMapRegionSelect, tp_province):
                        return False
                    else:
                        itt.wait_until_stable()
                        wait_until_appear(IconUIBigmap)
                else:
                    # 如果目标province在当前页面，需要判断是否已经展开
                    if tp_province == "心愿原野":
                        expand_province_dropdown(tp_province, "纪念山地", text_box_dict)
                    elif tp_province == "伊赞之土":
                        expand_province_dropdown(tp_province, "巨木之森", text_box_dict)

                if tp_province in ["星海"]:
                    self.update_region_and_map_name()
                    return True
                else:
                    if scroll_find_click(AreaBigMapRegionSelect, tp_region):
                        itt.wait_until_stable()
                        wait_until_appear(IconUIBigmap)
                        self.update_region_and_map_name()
                        return True
                    else:
                        return False
            else:
                return True

    def bigmap_tp(self, posi: list, map_name: str) -> t.Tuple[float, float]:
        """传送到指定坐标。

        Args:
            posi (list)

        Returns:
            TianLiPosition: _description_
        """
        logger.debug(f'bigmap tp to: {posi}')
        ui_control.ensure_page(page_bigmap)
        target_teleporter = self.find_closest_teleporter(posi, map_name)
        tp_posi = target_teleporter.position
        tp_province = target_teleporter.province
        tp_region = target_teleporter.region

        self.maximize_bigmap_scale()
        switch_success = self._switch_to_area(tp_province, tp_region)
        itt.delay(0.5, comment="等待地图完全切换完成")
        self.maximize_bigmap_scale() # 切换区域后，地图缩放会变回默认，再给它放大回去
        if not switch_success:
            msg = f"地图切换到'{tp_province}-{tp_region}'失败，请确保已经解锁所有地图，比如“无忧岛、丹青屿这类”"
            logger.error(msg)
            raise Exception(msg)

        click_posi = self._move_bigmap(tp_posi)
        itt.move_and_click(click_posi, anchor=ANCHOR_CENTER)
        itt.wait_until_stable()
        button_text = itt.ocr_single_line(AreaBigMapTeleportButton)
        if button_text == "传送":
            AreaBigMapTeleportButton.click()
        elif button_text == "追踪":
            raise BigMapTPError("流转之柱未解锁")
        else:
            # 传送点和其他图标重合的情况下，如果点击传送点，会弹出选择菜单
            hsv_lower = [0, 0, 220]
            hsv_upper = [180, 15, 255]   # hsv阈值处理，排除地图背景图案和文字的干扰
            if scroll_find_click(AreaBigMapTeleporterSelect, target_teleporter.name, hsv_limit=(hsv_lower, hsv_upper)):
                itt.wait_until_stable()
                button_text = itt.ocr_single_line(AreaBigMapTeleportButton)
                if button_text == "传送":
                    AreaBigMapTeleportButton.click()
                elif button_text == "追踪":
                    raise BigMapTPError("流转之柱未解锁")
                else:
                    raise BigMapTPError("大地图传送失败")
            else:
                raise BigMapTPError("大地图传送失败")

        # 等待传送完成
        stop_flag = get_current_stop_flag()
        while not (ui_control.verify_page(page_main)) and not stop_flag.is_set():
            time.sleep(0.5)
        # itt.wait_until_stable(threshold=0.9)
        self.init_position(tp_posi) 
        itt.delay(0.5, comment="等待小地图彻底加载完毕")
        return tp_posi

nikki_map = Map()
logger.info(f"nikki map object created")

if __name__ == '__main__':
    # 传送到菇菇聚落
    # position = convert_GameLoc_to_PngMapPx([-495722.4375, -185020.03125], MAP_NAME_MIRALAND)
    # position = convert_GameLoc_to_PngMapPx([-523254.75,-156153.0], MAP_NAME_MIRALAND)
    # nikki_map.bigmap_tp(position, MAP_NAME_MIRALAND)
    # 传送到星海
    position = convert_GameLoc_to_PngMapPx([-35070.57421875, 44421.59765625], MAP_NAME_STARSEA)
    nikki_map.bigmap_tp(position, MAP_NAME_STARSEA)
    # 传送到心愿原野
    # position = convert_GameLoc_to_PngMapPx([-13172.34765625, -54273.6171875], MAP_NAME_MIRALAND)
    # nikki_map.bigmap_tp(position, MAP_NAME_MIRALAND)