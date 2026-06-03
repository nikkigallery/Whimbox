"""Windows screen-capture implementation using PrintWindow / win32."""
from __future__ import annotations

import ctypes
from typing import Any, Optional

import numpy as np
import win32gui
import win32ui

from whimbox.core.interfaces import CaptureManager


class WindowsCaptureManager(CaptureManager):
    """Captures a window using the PrintWindow win32 API."""

    def capture_window(self, native_handle: Any, pid: Optional[int]) -> Optional[np.ndarray]:
        hwnd: int = native_handle or 0
        if not hwnd:
            return None
        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return None

            hdc_window = win32gui.GetWindowDC(hwnd)
            hdc_mem = win32ui.CreateDCFromHandle(hdc_window)
            hdc_compat = hdc_mem.CreateCompatibleDC()

            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(hdc_mem, width, height)
            hdc_compat.SelectObject(bmp)

            ctypes.windll.user32.PrintWindow(hwnd, hdc_compat.GetSafeHdc(), 3)

            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)

            win32gui.DeleteObject(bmp.GetHandle())
            hdc_compat.DeleteDC()
            hdc_mem.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc_window)
            return img
        except Exception:
            return None
