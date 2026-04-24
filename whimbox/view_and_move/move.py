from whimbox.view_and_move.cvars import *
from whimbox.interaction.interaction_core import itt
from whimbox.ui.ui_assets import *
from whimbox.common.base_threading import AdvanceThreading
from whimbox.common.timer_module import AdvanceTimer
from whimbox.common.logger import logger
from whimbox.common.utils.img_utils import *
from whimbox.common.utils.posi_utils import *
from whimbox.common.keybind import keybind
import time
from enum import Enum

def get_move_mode_in_game(ret_rate=False) -> str:
    """判断当前的移动模式（目前只支持步行和跳跃）"""
    r = itt.get_img_existence(IconMovementWalk, ret_mode=IMG_RATE)
    if ret_rate:
        if r > 0.90:
            return MOVE_MODE_WALK, r
        else:
            return MOVE_MODE_JUMP, r
    else:
        if r > 0.90:
            return MOVE_MODE_WALK
        else:
            return MOVE_MODE_JUMP


class JumpState(Enum):
    IDLE = 0
    NORMAL_JUMP = 1
    PREPARE_DOUBLE_JUMP = 2
    DOUBLE_JUMP = 3

class JumpController(AdvanceThreading):
    def __init__(self):
        super().__init__()
        self.while_sleep = 0.02
        self.normal_jump_timer = AdvanceTimer(0.3)
        self.prepare_double_jump_timer = AdvanceTimer(0.1)
        self._jump_state = JumpState.IDLE
        self.double_jump_begin_time = 0 # 二段跳开始时间

    def is_jumping(self):
        return self._jump_state != JumpState.IDLE

    def is_double_jumping(self):
        return self._jump_state == JumpState.DOUBLE_JUMP

    def clear_jump_state(self):
        self.normal_jump_timer.reset()
        self.prepare_double_jump_timer.reset()
        self._jump_state = JumpState.IDLE
        logger.debug('clear jump state')

    def start_jump(self):
        if self.is_jumping():
            logger.debug('already jumping')
            return
        itt.key_down(keybind.KEYBIND_JUMP)
        self.normal_jump_timer.reset()
        self.normal_jump_timer.start()
        self._jump_state = JumpState.NORMAL_JUMP
        logger.debug('start jump')

    def _prepare_double_jump(self):
        itt.key_up(keybind.KEYBIND_JUMP)
        self.prepare_double_jump_timer.reset()
        self.prepare_double_jump_timer.start()
        self._jump_state = JumpState.PREPARE_DOUBLE_JUMP
        logger.debug('prepare double jump')

    def _start_double_jump(self):
        itt.key_press(keybind.KEYBIND_JUMP)
        self.double_jump_begin_time = time.time()
        self._jump_state = JumpState.DOUBLE_JUMP
        logger.debug('start double jump')

    def stop_jump(self):
        if self._jump_state == JumpState.IDLE or get_move_mode_in_game() == MOVE_MODE_WALK:
            return
        if self._jump_state == JumpState.NORMAL_JUMP:
            itt.key_up(keybind.KEYBIND_JUMP)
            self.normal_jump_timer.reset()
            self._jump_state = JumpState.IDLE
            logger.debug('stop jump')
        elif self._jump_state == JumpState.PREPARE_DOUBLE_JUMP:
            self._jump_state = JumpState.IDLE
            logger.debug("stop prepare double jump")
        elif self._jump_state == JumpState.DOUBLE_JUMP:
            itt.key_press(keybind.KEYBIND_JUMP)
            self.double_jump_begin_time = 0
            self._jump_state = JumpState.IDLE
            logger.debug('stop double jump')

    def switch_jump(self):
        if self._jump_state == JumpState.NORMAL_JUMP and self.normal_jump_timer.reached():
            self._prepare_double_jump()
        elif self._jump_state == JumpState.PREPARE_DOUBLE_JUMP and self.prepare_double_jump_timer.reached():
            self._start_double_jump()

    def loop(self):
        self.switch_jump()


class MoveController(AdvanceThreading):
    def __init__(self):
        super().__init__()
        self.while_sleep = 0.02
        self.move_ahead_timer = None
        self.is_moving = False
        self.last_posi = None
        self.last_posi_time = 0
        # self.move_speed = 12 # 默认移动速度：12px/s
        self.move_speed_list = [12 for i in range(5)]
        self.loop_time_list = [0.2 for i in range(5)]

    def _update_move_speed(self, speed):
        self.move_speed_list.append(speed)
        self.move_speed_list.pop(0)

    def _estimate_move_speed(self):
        # 去掉最大值和最小值，剩余取平均值
        return (sum(self.move_speed_list) - max(self.move_speed_list) - min(self.move_speed_list)) / (len(self.move_speed_list) - 2)

    def _update_loop_time(self, once_loop_time):
        self.loop_time_list.append(once_loop_time)
        self.loop_time_list.pop(0)

    def _estimate_loop_time(self):
        loop_time = (sum(self.loop_time_list) - max(self.loop_time_list) - min(self.loop_time_list)) / (len(self.loop_time_list) - 2)
        return round(loop_time, 2)

    def start_move_ahead(self, current_posi, target_posi, offset, once_loop_time):
        # 更新历史移动速度
        now_time = time.time()
        if self.last_posi != None:
            distance = euclidean_distance(self.last_posi, current_posi)
            if distance > 1:
                cost_time = now_time - self.last_posi_time
                move_speed = distance / cost_time
                self._update_move_speed(move_speed)
        self.last_posi = current_posi
        self.last_posi_time = now_time

        # 更新运行时间
        if once_loop_time > 0:
            self._update_loop_time(once_loop_time)

        # 估算移动时间
        speed = self._estimate_move_speed()
        target_dist = euclidean_distance(current_posi, target_posi)
        loop_time = self._estimate_loop_time()
        duration = target_dist / speed - loop_time
        if duration < 0.05:
            duration = 0.05

        # 开始移动
        self.start_simple_move_ahead(duration)
        # logger.debug(f'start move ahead, duration: {duration}, loop_time: {loop_time}')

    def start_simple_move_ahead(self, duration):
        itt.key_down(keybind.KEYBIND_FORWARD)
        self.is_moving = True
        self.move_ahead_timer = AdvanceTimer(duration).start()

    def stop_move_ahead(self):
        self.is_moving = False
        self.move_ahead_timer = None
        self.last_posi = None # 让下次开始移动时，速度延用停止移动前的估算速度
        itt.key_up(keybind.KEYBIND_FORWARD)
        # logger.debug('stop move ahead')

    def switch_move(self):
        if self.is_moving and self.move_ahead_timer.reached():
            itt.key_up(keybind.KEYBIND_FORWARD)
            self.is_moving = False

    def loop(self):
        self.switch_move()

if __name__ == "__main__":
    # jump_controller = JumpController()
    # jump_controller.start()
    # while True:
    #     jump_controller.start_jump()
    #     time.sleep(1)
    #     jump_controller.stop_jump()
    #     time.sleep(3)

    while True:
        print(get_move_mode_in_game(ret_rate=True))
        time.sleep(0.3)