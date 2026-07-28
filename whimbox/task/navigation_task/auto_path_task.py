"""自动跑图"""
from whimbox.task.task_template import *
from whimbox.interaction.interaction_core import itt
import time, copy
from whimbox.common.path_lib import *
from whimbox.task.navigation_task.common import *
from whimbox.map.map import nikki_map
from whimbox.view_and_move.view import *
from whimbox.view_and_move.move import *
from whimbox.ability.ability import ability_manager
from whimbox.action.pickup import PickupTask
from whimbox.action.catch_insect import CatchInsectTask
from whimbox.action.floral_insect import FloralInsectTask
from whimbox.action.clean_animal import CleanAnimalTask
from whimbox.action.fairy_animal import FairyAnimalTask
from whimbox.action.fishing import FishingTask, FISHING_TYPE_MIRALAND, FISHING_TYPE_HOME
from whimbox.common.base_threading import BaseThreading
from whimbox.common.keybind import keybind
from whimbox.common.scripts_manager import *
from whimbox.map.convert import convert_GameLoc_to_PngMapPx
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.ability.cvar import *


class AutoPathClickSkipMonitor(BaseThreading):
    """自动跑图期间轻量检测跳过按钮。"""

    def __init__(self):
        super().__init__("auto_path_click_skip_monitor")
        self.while_sleep = 0.2
        self.last_key_press_time = 0

    def loop(self):
        if not itt.get_img_existence(IconClickSkip):
            return
        else:
            time.sleep(0.1)
            itt.key_press(keybind.KEYBIND_INTERACTION)


class AutoPathTask(TaskTemplate):
    def __init__(
        self,
        session_id,
        path_record: PathRecord=None,
        path_name: str=None,
        excepted_num=None,
        should_magnet=False,
        loop_overrides: dict[str, int] | None = None,
    ):
        super().__init__(session_id=session_id, name="auto_path_task")
        self.excepted_num = excepted_num # 期望的素材数量，获取到该数量后就停止
        self.should_magnet = should_magnet
        self.loop_overrides = loop_overrides or {}
        self.step_sleep = 0.01
        if path_record is not None:
            self.path_info = path_record.info
            self.path_points = copy.deepcopy(path_record.points)
            self.path_loops = copy.deepcopy(path_record.loops)
        elif path_name is not None:
            path_record = scripts_manager.query_path(path_name=path_name, return_one=True)
            if path_record is None:
                raise ValueError(f"路线\"{path_name}\"不存在，请先下载该路线")
            self.path_info = path_record.info
            self.path_points = copy.deepcopy(path_record.points)
            self.path_loops = copy.deepcopy(path_record.loops)
        else:
            raise ValueError("path_record和path_name不能同时为空")
        
        if self.path_info.version not in ("2.0", "2.1"):
            raise ValueError("路线版本不匹配，请更新路线")
        
        # 路线脚本中的坐标为游戏原生坐标，whimbox使用时需要转换为图片像素坐标
        for point in self.path_points:
            pngmap_position = convert_GameLoc_to_PngMapPx(point.position, self.path_info.map)
            point.position = [pngmap_position[0], pngmap_position[1]]

        self._init_loop_segments()
        
        # 各种状态记录
        self.stuck_time = None
        self.stuck_position = None
        self.has_try_break_stuck = False
        self.last_position = None
        self.curr_position = None
        self.curr_target_point_id = 0
        self.target_point: PathPoint = None
        self.need_move_mode = MOVE_MODE_WALK
        self.last_need_move_mode = MOVE_MODE_WALK
        self.current_game_move_mode = MOVE_MODE_WALK
        self.once_loop_time = 0
        self.last_teleport_point_id = 0

        # 各类材料获取任务的结果记录
        self.material_count_dict = {}
        # 动作控制器线程
        self.move_controller = None
        self.jump_controller = None
        self.click_skip_monitor = None

        # 一些常量
        self.walk2jump_stop_time = 0.5
        self.jump2walk_stop_time = 0.2
        self.offset = 2 # 当距离必经点offset以内，就视作已经到达

    def merge_material_count_dict(self, material_count_dict):
        if material_count_dict is None:
            return
        for key, value in material_count_dict.items():
            if key in self.material_count_dict:
                self.material_count_dict[key] += value
            else:
                self.material_count_dict[key] = value

    def _init_loop_segments(self):
        point_id_to_index = {
            point.id: index for index, point in enumerate(self.path_points)
        }
        self.loop_by_end_index: dict[int, dict] = {}
        self.loop_states: dict[str, dict] = {}
        for segment in self.path_loops:
            override = self.loop_overrides.get(segment.id)
            if override is not None:
                if not isinstance(override, int) or override < 0:
                    raise ValueError(f"循环分段{segment.id}的覆盖次数必须是非负整数")
                segment.loop_count = override

            start_index = point_id_to_index[segment.start_point_id]
            end_index = point_id_to_index[segment.end_point_id]
            start_point = self.path_points[start_index]
            end_point = self.path_points[end_index]
            return_mode = segment.return_mode
            if return_mode == "auto":
                return_mode = (
                    "teleport" if start_point.action == ACTION_TELEPORT else "nearby"
                )
            if return_mode == "teleport" and start_point.action != ACTION_TELEPORT:
                raise ValueError(
                    f"循环分段{segment.id}使用传送返回时，起点必须是传送点"
                )
            runtime_segment = {
                "segment": segment,
                "start_index": start_index,
                "end_index": end_index,
                "return_mode": return_mode,
            }
            self.loop_by_end_index[end_index] = runtime_segment
            self.loop_states[segment.id] = {
                "completed_count": 0,
                "finished": False,
            }

    def _has_reached_expected_num(self):
        return (
            self.excepted_num is not None
            and self.path_info.target
            and self.path_info.target in self.material_count_dict
            and self.material_count_dict[self.path_info.target] >= self.excepted_num
        )

    def _handle_loop_segment_end(self) -> bool:
        runtime_segment = self.loop_by_end_index.get(self.curr_target_point_id)
        if runtime_segment is None or self._has_reached_expected_num():
            return False

        segment = runtime_segment["segment"]
        state = self.loop_states[segment.id]
        if state["finished"]:
            return False

        state["completed_count"] += 1
        total_text = "∞" if segment.loop_count == 0 else str(segment.loop_count)
        self.log_to_gui(
            f"循环分段「{segment.name or segment.id}」"
            f"完成第 {state['completed_count']}/{total_text} 轮"
        )
        if segment.loop_count > 0 and state["completed_count"] >= segment.loop_count:
            state["finished"] = True
            return False

        self.stop_move()
        self.change_to_walk()
        self.last_position = None
        self.curr_position = None
        self.clear_stuck()
        self.curr_target_point_id = runtime_segment["start_index"]
        self.target_point = self.path_points[self.curr_target_point_id]
        self.need_move_mode = MOVE_MODE_WALK
        self.last_need_move_mode = MOVE_MODE_WALK
        self.current_game_move_mode = MOVE_MODE_WALK
        return True

    def task_stop(self, message="手动停止跑图"):
        if not self.need_stop():
            super().task_stop(message=message)

    def _update_next_target_point(self):
        """更新下一个必经点"""
        if self.curr_target_point_id < len(self.path_points) - 1:
            for index in range(self.curr_target_point_id+1, len(self.path_points)):
                if self.path_points[index].point_type == POINT_TYPE_TARGET:
                    self.curr_target_point_id = index
                    self.target_point = self.path_points[index]
                    return
    
    def start_move(self, current_posi, target_posi, offset):
        if self.move_controller:
            self.move_controller.start_move_ahead(current_posi, target_posi, offset, self.once_loop_time)

    def stop_move(self):
        if self.move_controller:
            self.move_controller.stop_move_ahead()

    def is_moving(self):
        if self.move_controller:
            return self.move_controller.is_moving

    def change_to_jump(self):
        """切换到跳跃模式"""
        if self.jump_controller:
            self.current_game_move_mode, rate = get_move_mode_in_game(ret_rate=True)
            if self.current_game_move_mode == MOVE_MODE_WALK:
                logger.debug(f"change to jump, rate: {rate}")
                # 游戏中二段跳瞬间，会出现一帧WALK状态的图标，所以这里还要判断连续两帧都是WALK，避免误判
                if self.jump_controller.is_double_jumping() \
                    and self.jump_controller.double_jump_begin_time \
                    and time.time() - self.jump_controller.double_jump_begin_time > 0.2:
                        self.jump_controller.clear_jump_state()
                self.jump_controller.start_jump()
            # 如果游戏中是跳跃图标，但是控制器不在跳跃，就说明被什么机制弹起来了或是下落中，触发一下二段跳
            elif self.current_game_move_mode == MOVE_MODE_JUMP and (not self.jump_controller.is_jumping()):
                self.jump_controller._start_double_jump()

    def change_to_walk(self):
        """切换到行走模式"""
        if self.jump_controller:
            self.current_game_move_mode, rate = get_move_mode_in_game(ret_rate=True)
            if self.current_game_move_mode == MOVE_MODE_JUMP:
                logger.debug(f"change to walk, rate: {rate}")
                self.jump_controller.stop_jump()
            # 有可能游戏中已经落地了，但是脚本中还记录当前为跳跃状态，所以强制清除跳跃
            elif self.current_game_move_mode == MOVE_MODE_WALK and self.jump_controller.is_jumping():
                self.jump_controller.clear_jump_state()


    def get_need_ability_list(self):
        action_to_ability_map = {
            ACTION_FLOURISH: ABILITY_NAME_FLOURISH,
            ACTION_CATCH_INSECT: ABILITY_NAME_INSECT,
            ACTION_FLORAL_INSECT: ABILITY_NAME_INSECT,
            ACTION_CLEAN_ANIMAL: ABILITY_NAME_ANIMAL,
            ACTION_FISHING: ABILITY_NAME_FISH,
            ACTION_FISHING_STAR: ABILITY_NAME_STAR_COLLECT,
            ACTION_BIG: ABILITY_NAME_BIG,
            ACTION_SHAPESHIFTING: ABILITY_NAME_SHAPESHIFTING,
        }
        need_ability_set = set()
        for point in self.path_points:
            if point.action and point.action in action_to_ability_map:
                need_ability_set.add(action_to_ability_map[point.action])
        if ABILITY_NAME_FISH in need_ability_set:
            if global_config.get_bool("OneDragon", "start_rhythms"):
                need_ability_set.add(ABILITY_NAME_RHYTHMS)
        if self.should_magnet:
            need_ability_set.add(ABILITY_NAME_SHAPESHIFTING)
        return list(need_ability_set)

    @register_step("初始化中……")
    def step0(self):
        # 启动动作控制线程
        self.jump_controller = JumpController()
        self.move_controller = MoveController()
        self.click_skip_monitor = AutoPathClickSkipMonitor()
        self.click_skip_monitor.add_stop_func(self.need_stop)
        self.jump_controller.start_threading()
        self.move_controller.start_threading()
        self.click_skip_monitor.start_threading()
        # 初始化能力盘
        self.log_to_gui("初始化能力轮盘")
        need_ability_list = self.get_need_ability_list()
        _, msg = ability_manager.init_need_ability(need_ability_list)
        self.log_to_gui(msg)
        # 初始化地图信息
        self.log_to_gui("初始化地图信息")
        nikki_map.reinit_smallmap()
        self.curr_position = nikki_map.get_position(use_cache=True)
        self.log_to_gui(f"开始跑图「{self.path_info.name}」")


    @register_step("自动跑图中……")
    def step1(self):
        itt.key_press("alt") # 开始跑图前按一下alt，避免游戏自身偶发bug，鼠标还在大世界界面中
        while not self.need_stop():
            start_time = time.time()
            is_end = self.inner_step_update_target()
            if is_end:
                break
            # 采集到预期数量的素材后，也可以停止跑图流程
            if self._has_reached_expected_num():
                break
            if self.need_stop():
                break
            self.inner_step_change_view()
            if self.need_stop():
                break
            self.inner_step_control_move()
            self.check_interruption()
            time.sleep(self.step_sleep)
            self.once_loop_time = time.time() - start_time
        return "step2"


    def check_stuck(self):
        if self.stuck_position is None:
            if euclidean_distance(self.curr_position, self.last_position) < 2:
                self.stuck_time = time.time()
                self.stuck_position = self.last_position
        else:
            if euclidean_distance(self.curr_position, self.stuck_position) < 2:
                # 连续几秒都在同一位置，则认为卡住了
                stuck_time = time.time() - self.stuck_time
                if stuck_time > 15:
                    raise Exception("卡住15秒了")
                elif stuck_time > 5 and (not self.has_try_break_stuck):
                    self.log_to_gui("卡住5秒了，尝试跳一下", is_loading=True)
                    self.jump_controller.stop_jump()
                    self.move_controller.stop_move_ahead()
                    time.sleep(1)
                    self.move_controller.start_simple_move_ahead(1)
                    self.jump_controller.start_jump()
                    time.sleep(1.5)
                    self.has_try_break_stuck = True
            else:
                self.clear_stuck()
        return False

    def clear_stuck(self):
        self.stuck_time = None
        self.stuck_position = None
        self.has_try_break_stuck = False


    def check_interruption(self):
        # 如果不在主界面了，可能是用户自己操作中断，或者跳进水里重置了
        need_log = True
        should_reinit = False
        interruption_time = 0
        while not itt.get_img_existence(IconPageMainFeature):
            # 连续检测到2次中断，才进行重置
            interruption_time += 1
            if interruption_time <= 1:
                pass
            else:
                should_reinit = True
                if need_log:
                    self.log_to_gui("意外中断，等待回到主界面……", is_loading=True)
                    need_log = False
            time.sleep(1)
        if should_reinit:
            self.log_to_gui("已回到主界面，重新定位坐标")
            nikki_map.reinit_smallmap()
            back_to_page_main()
            self.curr_position = nikki_map.get_position()
            self.last_position = None
            self.clear_stuck()

            target_point = self.path_points[self.curr_target_point_id]
            target_dist = euclidean_distance(
                self.curr_position, target_point.position)
            if target_dist >= not_teleport_offset:
                self.log_to_gui("已偏离路线太远，重新开始跑图")
                self.curr_target_point_id = 0
                self.target_point = self.path_points[0]
                self.need_move_mode = MOVE_MODE_WALK
                self.last_need_move_mode = MOVE_MODE_WALK
                self.current_game_move_mode = MOVE_MODE_WALK
                self.last_teleport_point_id = 0


    def inner_step_update_target(self):
        is_end = False
        self.last_position = self.curr_position
        self.curr_position = nikki_map.get_position()
        if self.check_stuck():
            raise Exception("卡住10秒了")
        self.target_point = self.path_points[self.curr_target_point_id]

        # 计算当前位置与必经点的距离
        # 只根据当前位置计算距离，会出现一种情况：
        # 已经走过了必经点，导致离必经点的距离会越走越远
        # 所以要结合上次的位置，计算离必经点的最小距离
        if self.last_position is not None:
            equal_points = linspace(self.last_position, self.curr_position)
            min_dist = euclidean_distance_plist(self.target_point.position, equal_points).min()
            target_dist = min_dist
        else:
            target_dist = euclidean_distance(self.target_point.position, self.curr_position)
        
        if target_dist <= self.offset:
            logger.debug(f"arrive target point {self.target_point.id}")

            # 处理各种ACTION
            if self.target_point.action:
                self.stop_move()
                self.change_to_walk()
                task_result = None
                if self.target_point.action == ACTION_PICK_UP:
                    if not self.path_info.test_mode:
                        pickup_task = PickupTask(session_id=self.session_id)
                        task_result = pickup_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不进行采集")
                        time.sleep(2)
                elif self.target_point.action == ACTION_FLOURISH:
                    if not self.path_info.test_mode:
                        from whimbox.action.flourish import FlourishTask
                        flourish_task = FlourishTask(session_id=self.session_id)
                        task_result = flourish_task.task_run()
                    else:
                        self.log_to_gui("测试跑图路线中，不进行芳间巡游")
                        time.sleep(2)
                elif self.target_point.action == ACTION_SHAPESHIFTING:
                    if not self.path_info.test_mode:
                        from whimbox.action.magnet import MagnetTask
                        magnet_task = MagnetTask(session_id=self.session_id)
                        task_result = magnet_task.task_run()
                    else:
                        self.log_to_gui("测试跑图路线中，不进行化万相")
                        time.sleep(2)
                elif self.target_point.action == ACTION_CATCH_INSECT:
                    if not self.path_info.test_mode:
                        excepted_count = int(self.target_point.action_params or 1)
                        catch_insect_task = CatchInsectTask(
                            self.session_id,
                            self.path_info.target,
                            expected_count=excepted_count)
                        task_result = catch_insect_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不进行捕虫")
                        time.sleep(2)
                elif self.target_point.action == ACTION_FLORAL_INSECT:
                    if not self.path_info.test_mode:
                        floral_insect_task = FloralInsectTask(self.session_id)
                        task_result = floral_insect_task.task_run()
                    else:
                        self.log_to_gui("测试跑图路线中，不进行捕虫")
                        time.sleep(2)
                elif self.target_point.action == ACTION_CLEAN_ANIMAL:
                    if not self.path_info.test_mode:
                        excepted_count = int(self.target_point.action_params or 1)
                        clean_animal_task = CleanAnimalTask(
                            self.session_id,
                            self.path_info.target,
                            expected_count=excepted_count)
                        task_result = clean_animal_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不进行清洁")
                        time.sleep(2)
                elif self.target_point.action == ACTION_FAIRY_ANIMAL:
                    if not self.path_info.test_mode:
                        fairy_animal_task = FairyAnimalTask(self.session_id)
                        task_result = fairy_animal_task.task_run()
                    else:
                        self.log_to_gui("测试跑图路线中，不进行清洁")
                        time.sleep(2)
                elif self.target_point.action == ACTION_FISHING:
                    if not self.path_info.test_mode:
                        fishing_task = FishingTask(
                            session_id=self.session_id, 
                            fishing_type=FISHING_TYPE_MIRALAND)
                        task_result = fishing_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不进行钓鱼")
                        time.sleep(2)
                elif self.target_point.action == ACTION_FISHING_STAR:
                    if not self.path_info.test_mode:
                        fishing_task = FishingTask(
                            session_id=self.session_id, 
                            fishing_type=FISHING_TYPE_HOME, 
                            already_material_count_dict=self.material_count_dict)
                        task_result = fishing_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不进行钓星")
                        time.sleep(2)
                elif self.target_point.action == ACTION_BIG:
                    from whimbox.action.big import BigTask
                    big_task = BigTask(session_id=self.session_id)
                    task_result = big_task.task_run()
                elif self.target_point.action == ACTION_WAIT:
                    wait_time = self.target_point.action_params
                    if wait_time is None:
                        wait_time = self.jump2walk_stop_time
                    time.sleep(float(wait_time))
                elif self.target_point.action == ACTION_KEY_CLICK:
                    itt.key_press(self.target_point.action_params)
                elif self.target_point.action == ACTION_MINIGAME:
                    macro_name = self.target_point.action_params
                    if macro_name is not None:
                        from whimbox.task.minigame_task.minigame_task import MinigameTask
                        minigame_task = MinigameTask(self.session_id, macro_name)
                        task_result = minigame_task.task_run()
                elif self.target_point.action == ACTION_MACRO:
                    if not self.path_info.test_mode:
                        macro_name = self.target_point.action_params
                        if macro_name is not None:
                            from whimbox.task.macro_task.run_macro_task import RunMacroTask
                            macro_task = RunMacroTask(self.session_id, macro_name)
                            task_result = macro_task.task_run()
                    else:
                        self.log_to_gui("测试跑图路线中，不进行宏操作")
                        time.sleep(2)
                elif self.target_point.action == ACTION_PLACE_ITEM:
                    from whimbox.task.daily_task.starsea_task.place_item_task import PlaceItemTask
                    place_item_task = PlaceItemTask(session_id=self.session_id)
                    task_result = place_item_task.task_run()
                elif self.target_point.action == ACTION_GROUP_CHAT:
                    from whimbox.task.daily_task.starsea_task.group_chat_task import GroupChatTask
                    group_chat_task = GroupChatTask(session_id=self.session_id)
                    task_result = group_chat_task.task_run()
                elif self.target_point.action == ACTION_CHANGE_MUSIC:
                    from whimbox.task.daily_task.starsea_task.change_music_task import ChangeMusicTask
                    change_music_task = ChangeMusicTask(session_id=self.session_id)
                    task_result = change_music_task.task_run()
                elif self.target_point.action == ACTION_PICKUP_BOTTLE:
                    if not self.path_info.test_mode:
                        from whimbox.task.daily_task.starsea_task.pickup_bottle_task import PickupBottleTask
                        pickup_bottle_task = PickupBottleTask(session_id=self.session_id)
                        task_result = pickup_bottle_task.task_run()
                        self.merge_material_count_dict(task_result.data)
                    else:
                        self.log_to_gui("测试跑图路线中，不拾取漂流瓶")
                        time.sleep(2)
                elif self.target_point.action == ACTION_DELIVERY_BOTTLE:
                    from whimbox.task.daily_task.starsea_task.delivery_bottle_task import DeliveryBottleTask
                    delivery_bottle_task = DeliveryBottleTask(session_id=self.session_id)
                    task_result = delivery_bottle_task.task_run()
                elif self.target_point.action == ACTION_TAKE_PHOTO:
                    from whimbox.task.photo_task.daily_photo_task import DailyPhotoTask
                    daily_photo_task = DailyPhotoTask(session_id=self.session_id)
                    task_result = daily_photo_task.task_run()
                elif self.target_point.action == ACTION_TRANS_ANIMAL:
                    from whimbox.task.daily_task.starsea_task.trans_animal_task import TransAnimalTask
                    trans_animal_task = TransAnimalTask(
                        session_id=self.session_id,
                        times=int(self.target_point.action_params or 1),
                    )
                    task_result = trans_animal_task.task_run()
                    
                if task_result is not None and task_result.status != STATE_TYPE_SUCCESS:
                    self.update_task_result(status=STATE_TYPE_FAILED, message=task_result.message)
                
                # 如果进行过动作就清除卡住状态，因为有些动作是很耗时的
                self.clear_stuck()

            if self._handle_loop_segment_end():
                return False

            if self.curr_target_point_id >= len(self.path_points) - 1:
                # 走到终点了
                is_end = True
            else:
                # 当行动模式切换时停一下，避免因为状态切换时图标显示比较乱而错判
                self.need_move_mode = self.target_point.move_mode
                if self.is_moving() and self.target_point.action != ACTION_WAIT:
                    if self.last_need_move_mode == MOVE_MODE_WALK and self.need_move_mode == MOVE_MODE_JUMP:
                        self.stop_move()
                        time.sleep(self.walk2jump_stop_time)
                    elif self.last_need_move_mode == MOVE_MODE_JUMP and self.need_move_mode == MOVE_MODE_WALK:
                        self.stop_move()
                        time.sleep(self.jump2walk_stop_time)
                
                self.last_need_move_mode = self.need_move_mode
                self._update_next_target_point()
        
        if self.target_point.action == ACTION_TELEPORT:
            # 记录经过的传送点，重试时可以从该传送点重试
            self.last_teleport_point_id = self.curr_target_point_id
            if euclidean_distance(self.target_point.position, self.curr_position) >= not_teleport_offset:
                self.log_to_gui(f"传送到附近的流转之柱")
                self.stop_move()
                self.change_to_walk()
                nikki_map.bigmap_tp(self.target_point.position, self.path_info.map)
                self.curr_position = nikki_map.get_position()
                self.clear_stuck()
            else:
                ui_control.ensure_page(page_main)
            # 校准视角旋转比例
            calibrate_view_rotation_ratio()

            if self.should_magnet and (not ability_manager.is_shapeshifting):
                from whimbox.action.magnet import MagnetTask
                magnet_task = MagnetTask(session_id=self.session_id)
                magnet_task.task_run()
        return is_end


    def inner_step_change_view(self):
        # 距离太近就不转视角了，避免观感太差
        self.curr_position = nikki_map.get_position()
        distance = euclidean_distance(self.curr_position, self.target_point.position)
        if distance < 0.5:
            return
        target_degree = calculate_posi2degree(self.curr_position, self.target_point.position)
        delta_degree = abs(calculate_delta_angle(nikki_map.get_rotation(), target_degree))
        # 如果要转很大的角度，需要先停下来
        if delta_degree >= 45 and self.is_moving():
            self.stop_move()
        change_view_to_angle(target_degree, offset=3, use_last_rotation=True)


    def inner_step_control_move(self):
        # # 有可能游戏中已经落地了，但是脚本中还记录当前为跳跃状态，所以强制清除跳跃
        # # 游戏中二段跳瞬间，会出现一帧WALK状态的图标，所以这里还要判断连续两帧都是WALK，避免误判
        # if game_move_mode == MOVE_MODE_WALK and self.jump_controller.is_double_jumping():
        #     time.sleep(0.1) 
        #     game_move_mode = get_move_mode_in_game()
        #     if game_move_mode == MOVE_MODE_WALK:
        #         self.jump_controller.clear_jump_state()
            
        if self.need_move_mode == MOVE_MODE_WALK:
            self.change_to_walk()
        elif self.need_move_mode == MOVE_MODE_JUMP:
            self.change_to_jump()
        
        self.start_move(self.curr_position, self.target_point.position, self.offset)
        

    def clear_all(self):
        self.last_position = None
        self.curr_position = None
        # 恢复到最近的传送点
        self.curr_target_point_id = self.last_teleport_point_id
        self.target_point: PathPoint = None
        self.need_move_mode = MOVE_MODE_WALK
        self.last_need_move_mode = MOVE_MODE_WALK
        self.current_game_move_mode = MOVE_MODE_WALK
        self.once_loop_time = 0

        if self.click_skip_monitor is not None:
            self.click_skip_monitor.stop_threading()
            self.click_skip_monitor.join()
            self.click_skip_monitor = None

        self.stop_move()
        self.change_to_walk()
        if self.jump_controller is not None and self.move_controller is not None:
            self.jump_controller.stop_threading()
            self.move_controller.stop_threading()
            self.jump_controller.join()
            self.move_controller.join()
            self.jump_controller = None
            self.move_controller = None


    @register_step("结束自动跑图")
    def step2(self):
        loop_summaries = []
        for segment in self.path_loops:
            state = self.loop_states[segment.id]
            loop_summaries.append(
                f"{segment.name or segment.id} {state['completed_count']}轮"
            )
        if len(self.material_count_dict) > 0:
            message = "自动跑图完成，获得材料："
            res = []
            for material_name, count in self.material_count_dict.items():
                res.append(f"{material_name} x {count}")
            message += ", ".join(res)
        else:
            message = "自动跑图完成"
        if loop_summaries:
            message += "；循环：" + "，".join(loop_summaries)
        self.update_task_result(message=message)


    def handle_finally(self):
        super().handle_finally()
        self.clear_all()


if __name__ == "__main__":
    # task = AutoPathTask(session_id="debug", path_name="测试卡住2", should_magnet=False)
    task = AutoPathTask(session_id="debug", path_name="鎏金蜜鎏金蜜南北绿豆")
    task_result = task.task_run()
    print(task_result.to_dict())

