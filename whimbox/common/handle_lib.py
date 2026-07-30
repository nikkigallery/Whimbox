"""Cross-platform process/window handle management.

ProcessHandler is a stateful wrapper around the native window handle for the
game process. All platform-specific operations are delegated to the
WindowManager obtained from the platform factory.
"""
import psutil
import time
from typing import Any, Optional

from whimbox.platform.factory import get_window_manager, get_path_manager
from whimbox.common.logger import logger


class ProcessHandler:
    """Manages a reference to a running game process.

    The *_native_handle* attribute is an opaque platform object:
    - Windows: an HWND integer (may be 0 for "not found")
    - macOS: an NSRunningApplication instance (or None)
    """

    def __init__(self, process_name: Optional[str] = None, pid: Optional[int] = None) -> None:
        self._mgr = get_window_manager()
        self.process_name = process_name
        self.pid = pid
        self._native_handle: Any = None

        if self.process_name is not None or self.pid is not None:
            self.refresh_handle()

    # ------------------------------------------------------------------
    # Handle access
    # ------------------------------------------------------------------

    def get_handle(self) -> Any:
        """Return the native handle (HWND on Windows, NSRunningApplication on macOS)."""
        return self._native_handle

    def refresh_handle(self) -> None:
        """Re-locate the process and update the native handle and PID."""
        native_handle = self._mgr.find_process(self.process_name, self.pid)

        if not self._mgr.is_alive(native_handle) and self.process_name is not None and self.pid is not None:
            native_handle = self._mgr.find_process(self.process_name, None)

        new_pid = self._mgr.get_pid(native_handle, self.process_name)
        if new_pid:
            self.pid = new_pid
            if not self._mgr.is_alive(native_handle):
                native_handle = self._mgr.find_process(self.process_name, new_pid)
        elif self.process_name is not None and not self._mgr.is_alive(native_handle):
            self.pid = None

        self._native_handle = native_handle

    # ------------------------------------------------------------------
    # Window state queries
    # ------------------------------------------------------------------

    def is_foreground(self) -> bool:
        return self._mgr.is_foreground(self._native_handle, self.pid)

    def is_minimized(self) -> bool:
        return self._mgr.is_minimized(self._native_handle)

    def is_alive(self) -> bool:
        return self._mgr.is_alive(self._native_handle)

    # ------------------------------------------------------------------
    # Window state mutations
    # ------------------------------------------------------------------

    def set_foreground(self) -> None:
        self._mgr.set_foreground(self._native_handle, self.pid, self.process_name)

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def _get_process_pid(self) -> Optional[int]:
        if self.pid is not None:
            return self.pid
        pid = self._mgr.get_pid(self._native_handle, self.process_name)
        if pid:
            self.pid = pid
        return pid

    def close_handle(self) -> None:
        """Close the application gracefully, escalating to process termination."""
        pid = self._get_process_pid()
        process: Optional[psutil.Process] = None
        if pid is not None:
            try:
                process = psutil.Process(pid)
            except psutil.NoSuchProcess:
                process = None
            except Exception as exc:
                logger.warning(f"获取进程对象失败: {exc}")

        try:
            if self.is_alive():
                self._mgr.close(self._native_handle)
        except Exception as exc:
            logger.error(exc)

        for _ in range(10):
            if process is not None:
                try:
                    if not process.is_running():
                        self.refresh_handle()
                        return
                except psutil.NoSuchProcess:
                    self.refresh_handle()
                    return
                except Exception as exc:
                    logger.warning(f"检查进程状态失败: {exc}")
                    break
            elif not self.is_alive():
                self.refresh_handle()
                return
            time.sleep(0.2)

        if process is None:
            return

        try:
            logger.warning(f"进程未在等待时间内退出，尝试结束进程: pid={process.pid}")
            process.terminate()
            try:
                process.wait(timeout=2)
            except psutil.TimeoutExpired:
                logger.warning(f"进程未在超时内退出，强制结束: pid={process.pid}")
                process.kill()
                process.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        except Exception as exc:
            logger.error(f"结束进程失败: {exc}")
        finally:
            self.refresh_handle()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def check_shape(self) -> tuple[bool, int, int]:
        """Return (valid, width, height) for the game window."""
        if not self.is_alive():
            return False, 0, 0
        width, height = self._mgr.get_window_size(self._native_handle, self.pid)
        if width <= 0:
            return False, 0, 0
        if 1.55 < width / height < 1.80:
            # 支持16:9和16:10分辨率
            # 有些用户在特定显示器和缩放下会生成奇怪的1920x1081分辨率，增加宽容度
            return True, width, height
        return False, width, height


HANDLE_OBJ = ProcessHandler(get_path_manager().get_process_name())

if __name__ == '__main__':
    pass
