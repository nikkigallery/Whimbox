"""Windows input injection using win32api / virtual key codes."""
from __future__ import annotations

import ctypes
import string
from typing import Optional

import win32api
import win32con
import win32gui

from whimbox.core.interfaces import InputManager
from whimbox.interaction.vkcode import VK_CODE

VkKeyScanA = ctypes.windll.user32.VkKeyScanA


class WindowsInputManager(InputManager):
    """Injects mouse and keyboard events via win32api."""

    WHEEL_DELTA = 120

    _BUTTON_DOWN = {
        'left': win32con.MOUSEEVENTF_LEFTDOWN,
        'right': win32con.MOUSEEVENTF_RIGHTDOWN,
        'middle': win32con.MOUSEEVENTF_MIDDLEDOWN,
    }
    _BUTTON_UP = {
        'left': win32con.MOUSEEVENTF_LEFTUP,
        'right': win32con.MOUSEEVENTF_RIGHTUP,
        'middle': win32con.MOUSEEVENTF_MIDDLEUP,
    }

    def mouse_down(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        win32api.mouse_event(self._BUTTON_DOWN[button], 0, 0, 0, 0)

    def mouse_up(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        win32api.mouse_event(self._BUTTON_UP[button], 0, 0, 0, 0)

    def mouse_scroll(self, distance: int) -> None:
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, distance * self.WHEEL_DELTA, 0)

    def mouse_move_relative(self, dx: int, dy: int) -> None:
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, dy)

    def mouse_set_pos(self, x: int, y: int) -> None:
        win32api.SetCursorPos((x, y))

    def mouse_get_pos(self) -> tuple[int, int]:
        return win32api.GetCursorPos()

    def key_event(self, key: str, down: bool) -> None:
        key_name = key.lower()
        vk_code = self.get_virtual_keycode(key)
        if key_name == 'shift':
            sc = win32api.MapVirtualKey(win32con.VK_SHIFT, 0)
        elif key_name == 'right_control':
            sc = win32api.MapVirtualKey(vk_code, 0)
        else:
            sc = 0
        flags = win32con.KEYEVENTF_EXTENDEDKEY if key_name == 'right_control' else 0
        if not down:
            flags |= win32con.KEYEVENTF_KEYUP
        win32api.keybd_event(vk_code, sc, flags, 0)

    def get_virtual_keycode(self, key: str) -> int:
        if len(key) == 1 and key in string.printable:
            return VkKeyScanA(ord(key)) & 0xFF
        return VK_CODE[key.lower()]
