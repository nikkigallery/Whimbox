from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

from whimbox.common.logger import logger


_WH_MOUSE_LL = 14
_HC_ACTION = 0
_WM_QUIT = 0x0012
_WM_MOUSEWHEEL = 0x020A
_WM_MOUSEHWHEEL = 0x020E
_WM_MOUSEMOVE = 0x0200
_VK_LBUTTON = 0x01


class MouseWheelGuard:
    """Suppress selected mouse input while lightweight predicates are true."""

    def __init__(
        self,
        should_block: Callable[[], bool],
        on_blocked: Callable[[], None],
        should_block_left_drag: Callable[[], bool] | None = None,
        on_left_drag_blocked: Callable[[], None] | None = None,
    ) -> None:
        self._should_block = should_block
        self._on_blocked = on_blocked
        self._should_block_left_drag = should_block_left_drag
        self._on_left_drag_blocked = on_left_drag_blocked
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._callback = None
        self._startup_error = ""

    def start(self) -> None:
        if sys.platform != "win32":
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = ""
            thread = threading.Thread(
                target=self._message_loop,
                name="map-mask-wheel-guard",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        self._ready.wait(timeout=0.5)
        if self._startup_error:
            logger.warning(
                f"[map-mask-wheel] unavailable: {self._startup_error}"
            )

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            thread_id = self._thread_id
        if thread is None:
            return
        if thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                thread_id,
                _WM_QUIT,
                0,
                0,
            )
        if thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int,
            callback_type,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.GetMessageW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def low_level_mouse_proc(
            code: int,
            message: int,
            event_data: int,
        ) -> int:
            if code == _HC_ACTION and message in {
                _WM_MOUSEWHEEL,
                _WM_MOUSEHWHEEL,
            }:
                try:
                    if self._should_block():
                        self._on_blocked()
                        return 1
                except Exception:  # noqa: BLE001
                    # Hook callbacks must always fail open so mouse input cannot stick.
                    pass
            if code == _HC_ACTION and message == _WM_MOUSEMOVE:
                try:
                    if (
                        self._should_block_left_drag is not None
                        and user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000
                        and self._should_block_left_drag()
                    ):
                        if self._on_left_drag_blocked is not None:
                            self._on_left_drag_blocked()
                        return 1
                except Exception:  # noqa: BLE001
                    # Hook callbacks must always fail open so mouse input cannot stick.
                    pass
            return int(
                user32.CallNextHookEx(
                    self._hook,
                    code,
                    message,
                    event_data,
                )
            )

        callback = callback_type(low_level_mouse_proc)
        hook = None
        try:
            with self._lock:
                self._thread_id = int(kernel32.GetCurrentThreadId())
                self._callback = callback
            module = kernel32.GetModuleHandleW(None)
            hook = user32.SetWindowsHookExW(
                _WH_MOUSE_LL,
                callback,
                module,
                0,
            )
            if not hook:
                error = ctypes.get_last_error()
                self._startup_error = f"SetWindowsHookExW failed ({error})"
                return
            with self._lock:
                self._hook = hook
            logger.info("[map-mask-wheel] guard started")
            self._ready.set()

            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)
            with self._lock:
                self._hook = None
                self._callback = None
                self._thread_id = 0
                if self._thread is threading.current_thread():
                    self._thread = None
            self._ready.set()
            if hook:
                logger.info("[map-mask-wheel] guard stopped")
