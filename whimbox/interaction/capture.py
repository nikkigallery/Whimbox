"""Cross-platform window capture.

All platform-specific capture logic is delegated to the CaptureManager
obtained from the platform factory.
"""
import threading
import time

import cv2
import numpy as np

from whimbox.common import timer_module
from whimbox.common.logger import logger
from whimbox.common.cvars import DEBUG_MODE
from whimbox.platform.factory import get_capture_manager


class Capture:
    def __init__(self, hwnd_handler):
        self.hwnd_handler = hwnd_handler
        self.capture_cache = np.zeros((1080, 1920, 4), dtype="uint8")
        self.resolution = None
        self.max_fps = 30
        self.fps_timer = timer_module.Timer(diff_start_time=1)
        self.capture_cache_lock = threading.Lock()
        self.capture_times = 0
        self.cap_per_sec = timer_module.CyclicCounter(limit=3).start()
        self.last_cap_times = 0

    def _cover_privacy(self, img: np.ndarray) -> np.ndarray:
        return img

    def _normalize_shape(self, img: np.ndarray) -> np.ndarray:
        if img is None:
            return None
        if self._check_shape(img):
            self.resolution = img.shape[:2]
            if img.shape[:2] == (1080, 1920) and img.shape[2] == 4:
                return img
            else:
                new_width = 1920
                new_height = int(1920 / self.resolution[1] * self.resolution[0])
                new_img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
                if len(new_img.shape) == 3 and new_img.shape[2] == 3:
                    new_img = cv2.cvtColor(new_img, cv2.COLOR_BGR2BGRA)
                return new_img
        else:
            self.resolution = None
            return None

    def _get_capture(self) -> np.ndarray:
        pass

    def _check_shape(self, img: np.ndarray):
        return True

    def capture(self, force=False) -> np.ndarray:
        """供外部调用的截图接口

        Args:
            force: 无视帧率限制，强制截图
        """
        if DEBUG_MODE:
            r = self.cap_per_sec.count_times()
            if r:
                if r != self.last_cap_times:
                    logger.trace(f"capps: {r/3}")
                    self.last_cap_times = r
                elif r >= 10 * 3:
                    logger.trace(f"capps: {r/3}")
                elif r >= 20 * 3:
                    logger.debug(f"capps: {r/3}")
                elif r >= 40 * 3:
                    logger.info(f"capps: {r/3}")
        with self.capture_cache_lock:
            self._capture(force)
            cp = self.capture_cache.copy()
        return cp

    def _capture(self, force) -> None:
        if (self.fps_timer.get_diff_time() >= 1 / self.max_fps) or force:
            self.fps_timer.reset()
            self.capture_times += 1
            normalized_img = self._normalize_shape(self._get_capture())
            if normalized_img is not None:
                self.capture_cache = normalized_img


class PrintWindowCapture(Capture):
    """Platform-agnostic capture class.

    Delegates the actual pixel acquisition to the CaptureManager so that
    no platform-specific code lives here.
    """

    def __init__(self, hwnd_handler):
        super().__init__(hwnd_handler)
        self.max_fps = 30
        self._cap_mgr = get_capture_manager()

    def _check_shape(self, img: np.ndarray):
        if img is None:
            return False
        if len(img.shape) >= 3 and img.shape[2] >= 3 and img.shape[1] > 0 and 1.55 < img.shape[1] / img.shape[0] < 1.80:
            # 支持16:9和16:10分辨率
            # 有些用户在特定显示器和缩放下会生成奇怪的1920x1081分辨率，增加宽容度
            return True
        else:
            logger.info("游戏分辨率异常: " + str(img.shape))
            return False

    def _get_capture(self):
        return self._cap_mgr.capture_window(
            self.hwnd_handler.get_handle(),
            self.hwnd_handler.pid,
        )


if __name__ == '__main__':
    pass
