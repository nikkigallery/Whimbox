"""Cross-platform mouse and keyboard interaction.

All platform-specific input injection is delegated to the InputManager
obtained from the platform factory.
"""
import time

from whimbox.interaction.interaction_template import InteractionTemplate
from whimbox.interaction.vkcode import VK_CODE
from whimbox.common.cvars import *
from whimbox.platform.factory import get_input_manager, get_window_manager


class InteractionNormal(InteractionTemplate):

    def __init__(self, hwnd_handler):
        self.hwnd_handler = hwnd_handler
        self._input = get_input_manager()
        self._wm = get_window_manager()
        self.VK_CODE = VK_CODE
        self.WHEEL_DELTA = 120

    def left_click(self):
        self._input.mouse_down('left')
        time.sleep(0.1)
        self._input.mouse_up('left')

    def left_down(self):
        self._input.mouse_down('left')

    def left_up(self):
        self._input.mouse_up('left')

    def left_double_click(self, dt=0.05):
        self.left_click()
        time.sleep(dt)
        self.left_click()

    def right_down(self):
        self._input.mouse_down('right')

    def right_up(self):
        self._input.mouse_up('right')

    def right_click(self):
        self.right_down()
        time.sleep(0.1)
        self.right_up()

    def middle_down(self):
        self._input.mouse_down('middle')

    def middle_up(self):
        self._input.mouse_up('middle')

    def middle_click(self):
        self.middle_down()
        time.sleep(0.1)
        self.middle_up()

    def middle_scroll(self, distance):
        self._input.mouse_scroll(distance)

    def key_down(self, key):
        self._input.key_event(key, True)

    def key_up(self, key):
        self._input.key_event(key, False)

    def key_press(self, key):
        self.key_down(key)
        time.sleep(0.1)
        self.key_up(key)

    def smooth_move_relative(self, dx: int, dy: int, duration=0.2):
        distance = (dx**2 + dy**2) ** 0.5
        steps = max(2, int(distance / 5))
        step_x = dx / steps
        step_y = dy / steps
        delay = duration / steps
        for _ in range(steps):
            self._input.mouse_move_relative(int(step_x), int(step_y))
            time.sleep(delay)

    def smooth_move_absolute(self, target_x: int, target_y: int, duration=0.2):
        current_x, current_y = self._input.mouse_get_pos()
        dx = target_x - current_x
        dy = target_y - current_y
        distance = (dx**2 + dy**2) ** 0.5
        if distance < 5:
            self._input.mouse_set_pos(target_x, target_y)
            return
        steps = max(2, int(distance / 5))
        delay = duration / steps
        for i in range(1, steps + 1):
            progress = i / steps
            self._input.mouse_set_pos(
                int(current_x + dx * progress),
                int(current_y + dy * progress),
            )
            time.sleep(delay)

    def move_to(self, x: int, y: int, resolution=None, anchor=ANCHOR_TOP_LEFT, relative=False, smooth=False, smooth_duration=0.2):
        x = int(x)
        y = int(y)
        standard_w = 1920
        standard_h = 1080

        scale = (resolution[1] / standard_w) if resolution is not None else 1

        if relative:
            x = int(x * scale)
            y = int(y * scale)
            if smooth:
                self.smooth_move_relative(x, y, duration=smooth_duration)
            else:
                self._input.mouse_move_relative(x, y)
        else:
            actual_h = int(resolution[0] / scale) if resolution is not None else standard_h
            if "TOP" in anchor:
                pass
            elif "BOTTOM" in anchor:
                y += actual_h - standard_h
            elif "CENTER" in anchor:
                y += (actual_h - standard_h) // 2

            x = int(x * scale)
            y = int(y * scale)
            screen_x, screen_y = self._wm.client_to_screen(
                self.hwnd_handler.get_handle(), x, y
            )

            if smooth:
                self.smooth_move_absolute(screen_x, screen_y, duration=smooth_duration)
            else:
                self._input.mouse_set_pos(screen_x, screen_y)


KEY_DOWN = 'KeyDown'
KEY_UP = 'KeyUp'


class Operation:
    def __str__(self):
        return f'Operation: {self.key} {self.type}'

    def __init__(self, key: str, type, operation_start=time.time(), operation_end=time.time()):
        self.key = key
        self.type = type
        self.operation_start = operation_start
        self.operation_end = operation_end
        self.operated = False


if __name__ == '__main__':
    pass
