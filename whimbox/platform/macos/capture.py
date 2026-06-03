"""macOS screen capture using Quartz window bounds."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import Quartz
import Quartz.CoreGraphics as CG

from whimbox.core.interfaces import CaptureManager
from whimbox.common.logger import logger


class MacOSCaptureManager(CaptureManager):
    """Captures game window content via native macOS CGWindowListCreateImage."""

    def __init__(self) -> None:
        pass

    def _get_window_id(self, pid: Optional[int]) -> Optional[int]:
        if pid is None:
            return None
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll,
            Quartz.kCGNullWindowID,
        )
        for window in window_list:
            if window.get(Quartz.kCGWindowOwnerPID) == pid:
                layer = window.get(Quartz.kCGWindowLayer, 0)
                bounds = window.get(Quartz.kCGWindowBounds)
                if layer == 0 and bounds and bounds.get('Height', 0) > 100:
                    return window.get(Quartz.kCGWindowNumber)
        return None

    def capture_window(self, native_handle: Any, pid: Optional[int]) -> Optional[np.ndarray]:
        target_window_id = self._get_window_id(pid)
        if not target_window_id:
            logger.warning(f"MacOSCaptureManager: Could not find window ID for PID {pid}")
            return None

        cg_image = CG.CGWindowListCreateImage(
            CG.CGRectNull,
            CG.kCGWindowListOptionIncludingWindow,
            target_window_id,
            CG.kCGWindowImageBoundsIgnoreFraming
        )

        if cg_image:
            width = CG.CGImageGetWidth(cg_image)
            height = CG.CGImageGetHeight(cg_image)
            bytes_per_row = CG.CGImageGetBytesPerRow(cg_image)
            data_provider = CG.CGImageGetDataProvider(cg_image)
            data = CG.CGDataProviderCopyData(data_provider)
            
            img_data = np.frombuffer(data, dtype=np.uint8)
            img_array = img_data.reshape((height, bytes_per_row // 4, 4))
            img_array = img_array[:, :width, :]
            return img_array
            
        logger.warning("MacOSCaptureManager: Failed to create CGImage")
        return None
