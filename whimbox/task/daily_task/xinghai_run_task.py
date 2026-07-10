from whimbox.ability.ability import ability_manager, ABILITY_NAME_SHAPESHIFTING
from whimbox.task.task_template import *
from whimbox.interaction.interaction_core import itt
from whimbox.ui.page_assets import *
from whimbox.map.convert import convert_GameLoc_to_PngMapPx
from whimbox.map.map import nikki_map
from whimbox.map.detection.cvars import MAP_NAME_STARSEA
from whimbox.common.keybind import keybind
from whimbox.common.utils.ui_utils import *
from whimbox.task.navigation_task.auto_path_task import AutoPathTask

class XinghaiRunTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="xinghai_run_task")
        self.target_loc = None
        self.not_find_crystal_times = 0

    @register_step("传送到星海无界枢纽")
    def step0(self):
        map_loc = convert_GameLoc_to_PngMapPx([-35070.57421875, 44421.59765625], MAP_NAME_STARSEA)
        nikki_map.bigmap_tp(map_loc, MAP_NAME_STARSEA)

    @register_step("摇铃")
    def step1(self):
        itt.key_down(keybind.KEYBIND_BELL)
        time.sleep(4)
        itt.key_up(keybind.KEYBIND_BELL)
        wait_until_appear(IconPageMainFeature, retry_time=10)

    @register_step("查看星光结晶位置")
    def step2(self):

        def move_map(dst_posi):
            itt.move_to(dst_posi)
            itt.left_down()
            time.sleep(0.1)
            itt.move_to((1920/2, 1080/2), anchor=ANCHOR_CENTER, smooth=True)
            time.sleep(0.1)
            itt.left_up()
            time.sleep(0.1)

        def move_map_to_right_top_corner():
            nikki_map._move_bigmap((2329, 1534))

        # 加快进入地图的速度，避免结晶消失
        itt.key_press(keybind.KEYBIND_MAP)
        time.sleep(0.2)
        while not self.need_stop() and not itt.get_img_existence(IconUIBigmap):
            itt.key_press(keybind.KEYBIND_MAP)
            time.sleep(0.2)
        logger.info("进入地图成功")
        
        # 阈值0.9，搜索不在当前地图画面的结晶，并点击跳转
        box = find_game_img(GameImgStarCrystal, itt.capture(), threshold=0.90, scale=1)
        if box:
            if 1500 < box[0] and box[1] < 400:
                # 如果在右上角，可能会被地图ui覆盖无法点击
                logger.info("星光结晶在右上角，可能被右上角ui覆盖无法点击，移动地图到右上角")
                move_map_to_right_top_corner()
            else:
                logger.info("星光结晶不在当前地图画面，点击跳转")
                # 点击y轴第二个结晶图标，尽量保证跳转到结晶的中心
                boxes = find_game_img(GameImgStarCrystal, itt.capture(), threshold=0.90, scale=1, count=3)
                if boxes:
                    if len(boxes) == 1:
                        box = boxes[0]
                    elif len(boxes) > 1:
                        boxes.sort(key=lambda x: x[1])
                        box = boxes[1]
                    itt.move_and_click(area_center(box))
                    itt.wait_until_stable(threshold=0.9995)
                else:
                    logger.info("结晶已经消失")
        else:
            # 如果没有，可能已经在当前湖面，可能被右上角地图ui覆盖无法识别
            box =  find_game_img(GameImgStarCrystal, itt.capture(), threshold=0.70, scale=1)
            if not box:
                logger.info("没找到星光结晶，可能被右上角ui覆盖无法识别，移动地图到右上角")
                move_map_to_right_top_corner()
            else:
                if 1500 < box[0] and box[1] < 400:
                    logger.info("星光结晶在右上角，可能被右上角ui覆盖无法点击，移动地图到右上角")
                    move_map_to_right_top_corner()
                else:
                    logger.info("星光结晶就在当前画面，不需要任何操作")
        
        first_try_find = True
        while not self.need_stop():
            # 移动地图后，再次识别当前地图画面的结晶
            boxes = find_game_img(GameImgStarCrystal, itt.capture(), threshold=0.70, scale=1, count=3)

            if boxes and len(boxes) > 0:
                centers = [area_center(box) for box in boxes]
                # 计算三个box的中心坐标（重心）
                triangle_center_x = sum(center[0] for center in centers) / len(centers)
                triangle_center_y = sum(center[1] for center in centers) / len(centers)
                triangle_center = (triangle_center_x, triangle_center_y)
                logger.debug(f"星光结晶中心屏幕坐标: {triangle_center}")
                if euclidean_distance(triangle_center, itt.get_screen_center()) < 30:
                    break
            else:
                if first_try_find:
                    self.not_find_crystal_times += 1
                    if self.not_find_crystal_times > 1:
                        self.update_task_result(status=STATE_TYPE_FAILED, message="地图上未找到星光结晶")
                        return "step_finish"
                    else:
                        self.log_to_gui("未找到星光结晶，重试一遍")
                        back_to_page_main()
                        return "step1"
                else:
                    break
            first_try_find = False
            
            # 拖到屏幕中心
            move_map(triangle_center)

        self.target_loc = nikki_map.get_bigmap_posi()
        logger.debug(f"星光结晶地图坐标: {self.target_loc}")


    @register_step("开始跑图收集星光结晶")
    def step3(self):
        auto_path_dict = {
            "星海拾光_星光结晶收集_星梦群屿": (2865.0, 2155.0), # 已校准
            "星海拾光_星光结晶收集_泡泡梦屿": (3082.0, 1893.0), # 已校准
            "星海拾光_星光结晶收集_泡泡梦屿2": (3140, 1960),
            "星海拾光_星光结晶收集_无界枢纽": (1679.0, 2000.0), # 已校准
            "星海拾光_星光结晶收集_晶簇之谷": (2250.0, 1475.0), # 已校准
            "星海拾光_星光结晶收集_大舞台": (3282.8, 2437.6),
            "星海拾光_星光结晶收集_繁星之滨": (2434.4, 1659.2),
            "星海拾光_星光结晶收集_繁星之滨2": (2375, 1605),
        }
        for path_name, loc in auto_path_dict.items():
            if euclidean_distance(self.target_loc, loc) < 50:

                should_magnet = global_config.get_bool("OneDragon", "start_magnet")
                auto_path_task = AutoPathTask(session_id=self.session_id, path_name=path_name, should_magnet=should_magnet)
                task_result = auto_path_task.task_run()
                if task_result.status == STATE_TYPE_SUCCESS:
                    self.update_task_result(status=STATE_TYPE_SUCCESS, message="收集星光结晶成功")
                else:
                    self.update_task_result(status=STATE_TYPE_FAILED, message="收集星光结晶失败")
                return
        self.update_task_result(status=STATE_TYPE_FAILED, message="暂时没有这条收集路线，等俺更新~")

if __name__ == "__main__":
    task = XinghaiRunTask(session_id="debug")
    print(task.task_run())
        
        
