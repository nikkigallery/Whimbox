import threading
import time
import sys
import numpy as np
import cv2

from whimbox.common import timer_module
from whimbox.common.logger import logger
from whimbox.common.cvars import DEBUG_MODE

if sys.platform == 'win32':
    import win32ui
    import win32gui
    import ctypes
elif sys.platform == 'darwin':
    import mss

class Capture():
    def __init__(self, hwnd_handler):
        self.hwnd_handler = hwnd_handler
        self.capture_cache = np.zeros_like((1080,1920,3), dtype="uint8")
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
            if img.shape[:2] == (1080,1920) and img.shape[2] == 4:
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
    
    def _check_shape(self, img:np.ndarray):
        return True
        
    def capture(self, force=False) -> np.ndarray:
        if DEBUG_MODE:
            r = self.cap_per_sec.count_times()
            if r:
                if r != self.last_cap_times:
                    logger.trace(f"capps: {r/3}")
                    self.last_cap_times = r
                elif r >= 10*3:
                    logger.trace(f"capps: {r/3}")
                elif r >= 20*3:
                    logger.debug(f"capps: {r/3}")
                elif r >= 40*3:
                    logger.info(f"capps: {r/3}")
        with self.capture_cache_lock:
            self._capture(force)
            cp = self.capture_cache.copy()
        return cp
    
    def _capture(self, force) -> None:
        if (self.fps_timer.get_diff_time() >= 1/self.max_fps) or force:
            self.fps_timer.reset()
            self.capture_times += 1
            normalized_img = self._normalize_shape(self._get_capture())
            if normalized_img is not None:
                self.capture_cache = normalized_img

class PrintWindowCapture(Capture):
    def __init__(self, hwnd_handler):
        super().__init__(hwnd_handler)
        self.max_fps = 30
        if sys.platform == 'darwin':
            self.sct = mss.mss()

    def _check_shape(self, img:np.ndarray):
        if img is None: return False
        if len(img.shape) >= 3 and img.shape[2] >= 3 and img.shape[1] > 0 and 1.55<img.shape[1]/img.shape[0]<1.80:
            return True
        else:
            logger.info("游戏分辨率异常: "+str(img.shape))
            return False

    def _get_capture(self):
        if sys.platform == 'win32':
            hwnd = self.hwnd_handler.get_handle()
            if not hwnd: return None
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top

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
        elif sys.platform == 'darwin':
            monitor = self.sct.monitors[1]
            sct_img = self.sct.grab(monitor)
            img = np.array(sct_img)
            return img

if __name__ == '__main__':
    pass
