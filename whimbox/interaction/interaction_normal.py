import time
import sys

from whimbox.interaction.interaction_template import InteractionTemplate
from whimbox.interaction.vkcode import VK_CODE
from whimbox.common.cvars import *

if sys.platform == 'win32':
    import ctypes
    import win32api, win32con, win32gui
elif sys.platform == 'darwin':
    import Quartz

class InteractionNormal(InteractionTemplate):

    def __init__(self, hwnd_handler):
        self.hwnd_handler = hwnd_handler
        self.VK_CODE = VK_CODE
        self.WHEEL_DELTA = 120
        
        if sys.platform == 'win32':
            self.WM_MOUSEMOVE = 0x0200
            self.WM_LBUTTONDOWN = 0x0201
            self.WM_LBUTTONUP = 0x202
            self.WM_MOUSEWHEEL = 0x020A
            self.WM_RBUTTONDOWN = 0x0204
            self.WM_RBUTTONDBLCLK = 0x0206
            self.WM_RBUTTONUP = 0x0205
            self.WM_KEYDOWN = 0x100
            self.WM_KEYUP = 0x101
            self.GetDC = ctypes.windll.user32.GetDC
            self.CreateCompatibleDC = ctypes.windll.gdi32.CreateCompatibleDC
            self.GetClientRect = ctypes.windll.user32.GetClientRect
            self.CreateCompatibleBitmap = ctypes.windll.gdi32.CreateCompatibleBitmap
            self.SelectObject = ctypes.windll.gdi32.SelectObject
            self.BitBlt = ctypes.windll.gdi32.BitBlt
            self.SRCCOPY = 0x00CC0020
            self.GetBitmapBits = ctypes.windll.gdi32.GetBitmapBits
            self.DeleteObject = ctypes.windll.gdi32.DeleteObject
            self.ReleaseDC = ctypes.windll.user32.ReleaseDC
            self.PostMessageW = ctypes.windll.user32.PostMessageW
            self.MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW
            self.VkKeyScanA = ctypes.windll.user32.VkKeyScanA
        
    def _mac_mouse_event(self, event_type, mouse_button, x=None, y=None):
        if x is None or y is None:
            event = Quartz.CGEventCreate(None)
            pos = Quartz.CGEventGetLocation(event)
            x, y = pos.x, pos.y
        event = Quartz.CGEventCreateMouseEvent(
            None,
            event_type,
            (x, y),
            mouse_button
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def left_click(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventLeftMouseDown, Quartz.kCGMouseButtonLeft)
            time.sleep(0.1)
            self._mac_mouse_event(Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft)

    def left_down(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventLeftMouseDown, Quartz.kCGMouseButtonLeft)
    
    def left_up(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft)
    
    def left_double_click(self):
        self.left_click()
        time.sleep(0.05)
        self.left_click()
    
    def right_down(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventRightMouseDown, Quartz.kCGMouseButtonRight)

    def right_up(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight)

    def right_click(self):
        self.right_down()
        time.sleep(0.1)
        self.right_up()

    def middle_down(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventOtherMouseDown, Quartz.kCGMouseButtonCenter)
    
    def middle_up(self):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        else:
            self._mac_mouse_event(Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter)

    def middle_click(self):
        self.middle_down()
        time.sleep(0.1)
        self.middle_up()
    
    def middle_scroll(self, distance):
        if sys.platform == 'win32':
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, distance*self.WHEEL_DELTA, 0)
        else:
            event = Quartz.CGEventCreateScrollWheelEvent(
                None,
                Quartz.kCGScrollEventUnitLine,
                1,
                distance
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def _mac_key_event(self, keycode, down):
        event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def _get_mac_keycode(self, key):
        mapping = {
            'space': 49,
            'w': 13,
            'a': 0,
            's': 1,
            'd': 2,
            'e': 14,
            'f': 3,
            'r': 15,
            'q': 12,
            'esc': 53,
            'shift': 56,
            'alt': 58,
            'ctrl': 59,
        }
        if key in mapping: return mapping[key]
        return 0

    def key_down(self, key):
        if sys.platform == 'win32':
            vk_code = self.get_virtual_keycode(key)
            if key == 'shift':
                sc =  win32api.MapVirtualKey(win32con.VK_SHIFT, 0)
            else:
                sc = 0
            win32api.keybd_event(vk_code, sc, 0, 0)
        else:
            keycode = self._get_mac_keycode(key)
            self._mac_key_event(keycode, True)
    
    def key_up(self, key):
        if sys.platform == 'win32':
            vk_code = self.get_virtual_keycode(key)
            if key == 'shift':
                sc =  win32api.MapVirtualKey(win32con.VK_SHIFT, 0)
            else:
                sc = 0
            win32api.keybd_event(vk_code, sc, win32con.KEYEVENTF_KEYUP, 0)
        else:
            keycode = self._get_mac_keycode(key)
            self._mac_key_event(keycode, False)
    
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
        
        for i in range(steps):
            if sys.platform == 'win32':
                win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, int(step_x), int(step_y))
            else:
                event = Quartz.CGEventCreate(None)
                pos = Quartz.CGEventGetLocation(event)
                self._mac_mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, pos.x + int(step_x), pos.y + int(step_y))
            time.sleep(delay)
    
    def smooth_move_absolute(self, target_x: int, target_y: int, duration=0.2):
        if sys.platform == 'win32':
            current_x, current_y = win32api.GetCursorPos()
        else:
            event = Quartz.CGEventCreate(None)
            pos = Quartz.CGEventGetLocation(event)
            current_x, current_y = pos.x, pos.y
            
        dx = target_x - current_x
        dy = target_y - current_y
        distance = (dx**2 + dy**2) ** 0.5
        
        if distance < 5:
            if sys.platform == 'win32':
                win32api.SetCursorPos((target_x, target_y))
            else:
                self._mac_mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, target_x, target_y)
            return
        
        steps = max(2, int(distance / 5))
        delay = duration / steps
        
        for i in range(1, steps + 1):
            progress = i / steps
            intermediate_x = int(current_x + dx * progress)
            intermediate_y = int(current_y + dy * progress)
            if sys.platform == 'win32':
                win32api.SetCursorPos((intermediate_x, intermediate_y))
            else:
                self._mac_mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, intermediate_x, intermediate_y)
            time.sleep(delay)

    def move_to(self, x: int, y: int, resolution=None, anchor=ANCHOR_TOP_LEFT, relative=False, smooth=False, smooth_duration=0.2):
        x = int(x)
        y = int(y)
        standard_w = 1920
        standard_h = 1080

        if resolution is not None:
            scale = resolution[1] / standard_w
        else:
            scale = 1

        if relative:
            x = int(x * scale)
            y = int(y * scale)
            if smooth:
                self.smooth_move_relative(x, y, duration=smooth_duration)
            else:
                if sys.platform == 'win32':
                    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, x, y)
                else:
                    event = Quartz.CGEventCreate(None)
                    pos = Quartz.CGEventGetLocation(event)
                    self._mac_mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, pos.x + x, pos.y + y)
        else:
            if resolution is not None:
                actual_h = int(resolution[0] / scale)
            else:
                actual_h = standard_h
            if "TOP" in anchor:
                pass
            elif "BOTTOM" in anchor:
                y += actual_h - standard_h
            elif "CENTER" in anchor:
                y += (actual_h - standard_h) / 2
            else:
                pass

            x = int(x * scale)
            y = int(y * scale)
            
            if sys.platform == 'win32':
                screen_x, screen_y = win32gui.ClientToScreen(self.hwnd_handler.get_handle(), (x, y))
            else:
                app_pid = self.hwnd_handler.pid
                window_x, window_y = 0, 0
                if app_pid:
                    window_list = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
                    for window in window_list:
                        if window.get(Quartz.kCGWindowOwnerPID) == app_pid:
                            bounds = window.get(Quartz.kCGWindowBounds)
                            if bounds:
                                window_x = bounds.get('X', 0)
                                window_y = bounds.get('Y', 0)
                                break
                screen_x = window_x + x
                screen_y = window_y + y
            
            if smooth:
                self.smooth_move_absolute(screen_x, screen_y, duration=smooth_duration)
            else:
                if sys.platform == 'win32':
                    win32api.SetCursorPos((screen_x, screen_y))
                else:
                    self._mac_mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, screen_x, screen_y)

KEY_DOWN = 'KeyDown'
KEY_UP = 'KeyUp'

class Operation():
    def __str__(self):
        return f'Operation: {self.key} {self.type}'
    def __init__(self, key:str, type, operation_start=time.time(), operation_end = time.time()):
        self.key = key
        self.type = type
        self.operation_start = operation_start
        self.operation_end = operation_end
        self.operated = False

if __name__ == '__main__':
    pass
