"""Windows window management implementation using win32 APIs."""
from __future__ import annotations

import ctypes
import psutil
import time
from typing import Any, Optional

import win32api
import win32con
import win32gui
import win32process

from whimbox.core.interfaces import WindowManager
from whimbox.common.logger import logger


class WindowsWindowManager(WindowManager):
    """Implements WindowManager using win32 APIs."""

    def __init__(self) -> None:
        self._last_selection_log: tuple | None = None
        self._last_selection_log_at = 0.0

    def find_process(self, process_name: Optional[str], pid: Optional[int]) -> Optional[int]:
        """Return an HWND for the given process, or None."""
        if process_name is None and pid is not None:
            return self._get_hwnd_for_pid(pid)
        if process_name is not None:
            matching_pids: list[int] = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] == process_name:
                        matching_pids.append(proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if not matching_pids:
                return None

            windows = {
                candidate_pid: hwnd
                for candidate_pid in matching_pids
                if (hwnd := self._get_hwnd_for_pid(candidate_pid)) is not None
            }
            foreground_pid = None
            try:
                foreground_hwnd = win32gui.GetForegroundWindow()
                if foreground_hwnd:
                    _, foreground_pid = win32process.GetWindowThreadProcessId(foreground_hwnd)
            except Exception:
                pass

            if foreground_pid in windows:
                selected = windows[foreground_pid]
                reason = 'foreground'
            elif pid in windows:
                selected = windows[pid]
                reason = 'previous-pid'
            elif len(windows) == 1:
                selected = next(iter(windows.values()))
                reason = 'only-valid-window'
            else:
                selected = None
                reason = 'no-valid-window' if not windows else 'ambiguous-windows'

            self._log_window_selection(process_name, matching_pids, windows, selected, reason)
            return selected
        return None

    def _get_hwnd_for_pid(self, pid: int) -> Optional[int]:
        hwnds: list[int] = []

        def callback(hwnd: int, _: Any) -> bool:
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid and win32gui.IsWindowVisible(hwnd) and win32gui.GetParent(hwnd) == 0:
                    left, top, right, bottom = win32gui.GetClientRect(hwnd)
                    if right > left and bottom > top:
                        hwnds.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        if not hwnds:
            return None
        return max(hwnds, key=lambda hwnd: self._client_area(hwnd))

    @staticmethod
    def _client_area(hwnd: int) -> int:
        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            return max(0, right - left) * max(0, bottom - top)
        except Exception:
            return 0

    def _log_window_selection(
        self,
        process_name: str,
        matching_pids: list[int],
        windows: dict[int, int],
        selected: Optional[int],
        reason: str,
    ) -> None:
        if len(matching_pids) == 1 and selected is not None:
            return
        signature = (process_name, tuple(sorted((candidate_pid, windows.get(candidate_pid)) for candidate_pid in matching_pids)), selected, reason)
        now = time.monotonic()
        if signature == self._last_selection_log and now - self._last_selection_log_at < 60:
            return
        self._last_selection_log = signature
        self._last_selection_log_at = now
        candidates = ', '.join(
            f'pid={candidate_pid} {self._describe_window(windows.get(candidate_pid))}'
            for candidate_pid in matching_pids
        )
        message = f'进程窗口选择: {process_name}, reason={reason}, selected={selected or 0}, candidates=[{candidates}]'
        if selected is None:
            logger.warning(message)
        else:
            logger.info(message)

    @staticmethod
    def _describe_window(hwnd: Optional[int]) -> str:
        if not hwnd:
            return 'hwnd=0'
        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            return (
                f'hwnd={hwnd} class={win32gui.GetClassName(hwnd)} '
                f'client={right - left}x{bottom - top} minimized={bool(win32gui.IsIconic(hwnd))}'
            )
        except Exception:
            return f'hwnd={hwnd}'

    def get_pid(self, native_handle: Any, process_name: Optional[str]) -> Optional[int]:
        hwnd: int = native_handle or 0
        if hwnd and win32gui.IsWindow(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    return pid
            except Exception as exc:
                logger.warning(f'通过窗口句柄获取进程ID失败: {exc}')
        return None

    def is_foreground(self, native_handle: Any, pid: Optional[int]) -> bool:
        return bool(native_handle) and win32gui.GetForegroundWindow() == native_handle

    def has_foreground_process(self, process_name: str) -> bool:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return False
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name() == process_name
        except Exception:
            return False

    def is_minimized(self, native_handle: Any) -> bool:
        return bool(native_handle) and win32gui.IsIconic(native_handle)

    def set_foreground(self, native_handle: Any, pid: Optional[int], process_name: Optional[str]) -> None:
        hwnd: int = native_handle or 0

        def _activate(h: int) -> None:
            if win32gui.IsIconic(h):
                win32gui.ShowWindow(h, win32con.SW_RESTORE)

            fg_hwnd = win32gui.GetForegroundWindow()
            current_tid = win32api.GetCurrentThreadId()
            target_tid, _ = win32process.GetWindowThreadProcessId(h)
            fg_tid = 0
            if fg_hwnd:
                fg_tid, _ = win32process.GetWindowThreadProcessId(fg_hwnd)

            attached_fg = False
            attached_target = False

            def _safe_attach(src: int, dst: int, attach: bool, label: str) -> bool:
                if not src or not dst or src == dst:
                    return False
                try:
                    win32process.AttachThreadInput(src, dst, attach)
                    return True
                except Exception as exc:
                    logger.warning(f'AttachThreadInput {label} failed: {exc}')
                    return False

            try:
                attached_fg = _safe_attach(current_tid, fg_tid, True, 'foreground')
                attached_target = _safe_attach(current_tid, target_tid, True, 'target')
                win32gui.SetForegroundWindow(h)
            finally:
                if attached_target:
                    _safe_attach(current_tid, target_tid, False, 'target-detach')
                if attached_fg:
                    _safe_attach(current_tid, fg_tid, False, 'foreground-detach')

        try:
            if not self.is_alive(hwnd):
                raise Exception('游戏窗口不存在')
            _activate(hwnd)
            if self.is_foreground(hwnd, pid):
                return
            raise Exception('无法将游戏窗口前置')
        except Exception as exc:
            logger.error(exc)
            raise Exception('游戏窗口前置失败')

    def is_alive(self, native_handle: Any) -> bool:
        return bool(native_handle) and win32gui.IsWindow(native_handle)

    def close(self, native_handle: Any) -> None:
        if native_handle and self.is_alive(native_handle):
            try:
                win32gui.PostMessage(native_handle, win32con.WM_CLOSE, 0, 0)
            except Exception as exc:
                logger.error(exc)

    def get_window_size(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int]:
        hwnd: int = native_handle or 0
        if not hwnd:
            return 0, 0
        try:
            _, _, width, height = win32gui.GetClientRect(hwnd)
            return width, height
        except Exception:
            return 0, 0

    def get_window_rect(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int, int, int]:
        hwnd: int = native_handle or 0
        if not hwnd:
            return 0, 0, 0, 0
        try:
            rect = win32gui.GetClientRect(hwnd)
            left, top = win32gui.ClientToScreen(hwnd, (rect[0], rect[1]))
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            return left, top, width, height
        except Exception:
            return 0, 0, 0, 0

    def get_window_scale_factor(self, native_handle: Any, pid: Optional[int]) -> float:
        hwnd: int = native_handle or 0
        if not hwnd:
            return 1.0
        try:
            get_dpi_for_window = ctypes.windll.user32.GetDpiForWindow
            get_dpi_for_window.argtypes = [ctypes.c_void_p]
            get_dpi_for_window.restype = ctypes.c_uint
            dpi = int(get_dpi_for_window(hwnd))
            return dpi / 96.0 if dpi > 0 else 1.0
        except Exception:
            return 1.0

    def client_to_screen(self, native_handle: Any, x: int, y: int) -> tuple[int, int]:
        return win32gui.ClientToScreen(native_handle, (x, y))
