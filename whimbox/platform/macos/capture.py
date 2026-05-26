"""macOS screen capture using mss + Quartz window bounds."""
from __future__ import annotations

from typing import Any, Optional

import mss
import numpy as np
import Quartz

from whimbox.core.interfaces import CaptureManager


class MacOSCaptureManager(CaptureManager):
    """Captures game window content via mss (cross-process safe on macOS)."""

    def __init__(self) -> None:
        self._sct = mss.mss()

    def _get_window_bounds(self, pid: Optional[int]) -> Optional[dict]:
        if pid is None:
            return None
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in window_list:
            if window.get(Quartz.kCGWindowOwnerPID) == pid:
                layer = window.get(Quartz.kCGWindowLayer, 0)
                bounds = window.get(Quartz.kCGWindowBounds)
                if layer == 0 and bounds and bounds.get('Height', 0) > 100:
                    return bounds
        return None

    def capture_window(self, native_handle: Any, pid: Optional[int]) -> Optional[np.ndarray]:
        bounds = self._get_window_bounds(pid)
        if bounds:
            monitor = {
                'top': int(bounds.get('Y', 0)),
                'left': int(bounds.get('X', 0)),
                'width': int(bounds.get('Width', 0)),
                'height': int(bounds.get('Height', 0)),
            }
            if monitor['width'] > 0 and monitor['height'] > 0:
                sct_img = self._sct.grab(monitor)
                return np.array(sct_img)
        # Fall back to primary monitor
        sct_img = self._sct.grab(self._sct.monitors[1])
        return np.array(sct_img)
