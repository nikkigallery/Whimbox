"""macOS input injection using Quartz CGEvent APIs."""
from __future__ import annotations

import string
from typing import Optional

import Quartz

from whimbox.core.interfaces import InputManager
from whimbox.interaction.vkcode import VK_CODE

# macOS virtual key code mapping for common keys used by the game
_MAC_KEYCODE: dict[str, int] = {
    'space': 49, 'esc': 53, 'enter': 36, 'return': 36,
    'backspace': 51, 'delete': 51, 'tab': 48,
    'shift': 56, 'alt': 58, 'ctrl': 59, 'control': 59, 'cmd': 55,
    'up': 126, 'down': 125, 'left': 123, 'right': 124,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118,
    'f5': 96, 'f6': 97, 'f7': 98, 'f8': 100,
    'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5,
    'z': 6, 'x': 7, 'c': 8, 'v': 9, 'b': 11,
    'q': 12, 'w': 13, 'e': 14, 'r': 15, 'y': 16, 't': 17,
    '1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23,
    '=': 24, '9': 25, '7': 26, '-': 27, '8': 28, '0': 29,
    ']': 30, 'o': 31, 'u': 32, '[': 33, 'i': 34, 'p': 35,
    'l': 37, 'j': 38, "'": 39, 'k': 40, ';': 41,
    '\\': 42, ',': 43, '/': 44, 'n': 45, 'm': 46, '.': 47,
}

_BUTTON_TYPE_DOWN = {
    'left': Quartz.kCGEventLeftMouseDown,
    'right': Quartz.kCGEventRightMouseDown,
    'middle': Quartz.kCGEventOtherMouseDown,
}
_BUTTON_TYPE_UP = {
    'left': Quartz.kCGEventLeftMouseUp,
    'right': Quartz.kCGEventRightMouseUp,
    'middle': Quartz.kCGEventOtherMouseUp,
}
_BUTTON_ID = {
    'left': Quartz.kCGMouseButtonLeft,
    'right': Quartz.kCGMouseButtonRight,
    'middle': Quartz.kCGMouseButtonCenter,
}


class MacOSInputManager(InputManager):
    """Injects mouse and keyboard events via Quartz CGEvent."""

    def _get_cursor_pos(self) -> tuple[float, float]:
        event = Quartz.CGEventCreate(None)
        pos = Quartz.CGEventGetLocation(event)
        return pos.x, pos.y

    def _mouse_event(
        self,
        event_type: int,
        button_id: int,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ) -> None:
        if x is None or y is None:
            x, y = self._get_cursor_pos()
        event = Quartz.CGEventCreateMouseEvent(None, event_type, (x, y), button_id)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def mouse_down(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self._mouse_event(_BUTTON_TYPE_DOWN[button], _BUTTON_ID[button], x, y)

    def mouse_up(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self._mouse_event(_BUTTON_TYPE_UP[button], _BUTTON_ID[button], x, y)

    def mouse_scroll(self, distance: int) -> None:
        event = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitLine, 1, distance
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def mouse_move_relative(self, dx: int, dy: int) -> None:
        cx, cy = self._get_cursor_pos()
        self._mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, cx + dx, cy + dy)

    def mouse_set_pos(self, x: int, y: int) -> None:
        self._mouse_event(Quartz.kCGEventMouseMoved, Quartz.kCGMouseButtonLeft, x, y)

    def mouse_get_pos(self) -> tuple[int, int]:
        x, y = self._get_cursor_pos()
        return int(x), int(y)

    def key_event(self, key: str, down: bool) -> None:
        keycode = self.get_virtual_keycode(key)
        event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def get_virtual_keycode(self, key: str) -> int:
        key_lower = key.lower()
        if key_lower in _MAC_KEYCODE:
            return _MAC_KEYCODE[key_lower]
        # Fallback for unmapped printable characters
        if len(key) == 1 and key in string.printable:
            return ord(key.upper())
        return 0
