"""macOS window management using AppKit and Quartz."""
from __future__ import annotations

import subprocess
import time
from typing import Any, Optional

import psutil
import Quartz
from AppKit import NSApplicationActivateIgnoringOtherApps, NSWorkspace

from whimbox.core.interfaces import WindowManager
from whimbox.common.logger import logger


class MacOSWindowManager(WindowManager):
    """Implements WindowManager using AppKit/Quartz APIs."""

    def find_process(self, process_name: Optional[str], pid: Optional[int]) -> Any:
        """Return the NSRunningApplication for the given process, or None."""
        workspace = NSWorkspace.sharedWorkspace()
        for app in workspace.runningApplications():
            if pid is not None and app.processIdentifier() == pid:
                return app
            if process_name is not None and (
                app.bundleIdentifier() == process_name
                or app.localizedName() == process_name
            ):
                return app
        return None

    def get_pid(self, native_handle: Any, process_name: Optional[str]) -> Optional[int]:
        if native_handle is not None:
            return native_handle.processIdentifier()
        return None

    def is_foreground(self, native_handle: Any, pid: Optional[int]) -> bool:
        if native_handle is None or not pid:
            return False
        workspace = NSWorkspace.sharedWorkspace()
        front_app = workspace.frontmostApplication()
        if front_app and front_app.processIdentifier() == pid:
            return True
        # Fall back to Quartz layer check for the topmost large window
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in window_list:
            layer = window.get(Quartz.kCGWindowLayer, 0)
            bounds = window.get(Quartz.kCGWindowBounds)
            if layer == 0 and bounds and bounds.get('Height', 0) > 400 and bounds.get('Width', 0) > 400:
                return window.get(Quartz.kCGWindowOwnerPID) == pid
        return False

    def is_minimized(self, native_handle: Any) -> bool:
        # macOS minimised detection via Quartz is complex; return False as per POC
        return False

    def set_foreground(self, native_handle: Any, pid: Optional[int], process_name: Optional[str]) -> None:
        if not self.is_alive(native_handle):
            raise Exception("游戏窗口不存在")
        try:
            native_handle.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            time.sleep(0.5)
            if self.is_foreground(native_handle, pid):
                return
            bundle_id = native_handle.bundleIdentifier()
            if bundle_id:
                subprocess.run(['osascript', '-e', f'tell application id "{bundle_id}" to activate'])
            else:
                name = native_handle.localizedName()
                subprocess.run(['osascript', '-e', f'tell application "{name}" to activate'])
            time.sleep(0.5)
            if self.is_foreground(native_handle, pid):
                return
            front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            front_name = front_app.localizedName() if front_app else 'None'
            raise Exception(f"无法将游戏窗口前置，当前前置应用为: {front_name}")
        except Exception as exc:
            logger.error(exc)
            raise Exception("游戏窗口前置失败")

    def is_alive(self, native_handle: Any) -> bool:
        return native_handle is not None and not native_handle.isTerminated()

    def close(self, native_handle: Any) -> None:
        if self.is_alive(native_handle):
            try:
                native_handle.terminate()
            except Exception as exc:
                logger.error(exc)

    def _get_window_bounds(self, pid: Optional[int]) -> Optional[dict]:
        """Return the Quartz CGWindowBounds dict for the main window of *pid*."""
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

    def get_window_size(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int]:
        bounds = self._get_window_bounds(pid)
        if bounds:
            return int(bounds.get('Width', 0)), int(bounds.get('Height', 0))
        return 0, 0

    def get_window_rect(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int, int, int]:
        bounds = self._get_window_bounds(pid)
        if bounds:
            return (
                int(bounds.get('X', 0)),
                int(bounds.get('Y', 0)),
                int(bounds.get('Width', 0)),
                int(bounds.get('Height', 0)),
            )
        return 0, 0, 0, 0

    def get_window_scale_factor(self, native_handle: Any, pid: Optional[int]) -> float:
        return 1.0

    def client_to_screen(self, native_handle: Any, x: int, y: int) -> tuple[int, int]:
        """On macOS the Quartz origin is the screen origin, so client == screen."""
        pid = self.get_pid(native_handle, None)
        bounds = self._get_window_bounds(pid)
        if bounds:
            return int(bounds.get('X', 0)) + x, int(bounds.get('Y', 0)) + y
        return x, y
