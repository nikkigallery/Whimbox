"""Abstract base classes for platform-specific implementations.

All OS-specific logic must be isolated behind these interfaces.
No sys.platform checks should appear outside of whimbox/platform/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np


class WindowManager(ABC):
    """Abstracts all native window management operations.

    The *native_handle* parameter is an opaque platform object:
    - Windows: an HWND integer
    - macOS: an NSRunningApplication instance
    """

    @abstractmethod
    def find_process(self, process_name: Optional[str], pid: Optional[int]) -> Any:
        """Locate a process and return its native handle, or None if not found."""

    @abstractmethod
    def get_pid(self, native_handle: Any, process_name: Optional[str]) -> Optional[int]:
        """Resolve the PID from a native handle."""

    @abstractmethod
    def is_foreground(self, native_handle: Any, pid: Optional[int]) -> bool:
        """Return True if the process owns the foreground window."""

    @abstractmethod
    def is_minimized(self, native_handle: Any) -> bool:
        """Return True if the window is minimized/iconic."""

    @abstractmethod
    def set_foreground(self, native_handle: Any, pid: Optional[int], process_name: Optional[str]) -> None:
        """Bring the window to the foreground, raising on failure."""

    @abstractmethod
    def is_alive(self, native_handle: Any) -> bool:
        """Return True if the process/window still exists."""

    @abstractmethod
    def close(self, native_handle: Any) -> None:
        """Terminate or close the target window/process."""

    @abstractmethod
    def get_window_size(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int]:
        """Return (width, height) of the window client area."""

    @abstractmethod
    def get_window_rect(self, native_handle: Any, pid: Optional[int]) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) of the window in screen coordinates."""

    @abstractmethod
    def get_window_scale_factor(self, native_handle: Any, pid: Optional[int]) -> float:
        """Return the native-pixel to logical-coordinate scale factor."""

    @abstractmethod
    def client_to_screen(self, native_handle: Any, x: int, y: int) -> tuple[int, int]:
        """Convert client-area coordinates to screen coordinates."""


class CaptureManager(ABC):
    """Abstracts window/screen capture."""

    @abstractmethod
    def capture_window(self, native_handle: Any, pid: Optional[int]) -> Optional[np.ndarray]:
        """Capture the window and return a BGRA numpy array, or None on failure."""


class InputManager(ABC):
    """Abstracts mouse and keyboard injection."""

    # --- Mouse ---
    @abstractmethod
    def mouse_down(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Press a mouse button. button is 'left', 'right', or 'middle'."""

    @abstractmethod
    def mouse_up(self, button: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Release a mouse button."""

    @abstractmethod
    def mouse_scroll(self, distance: int) -> None:
        """Scroll the mouse wheel by *distance* units (positive = up)."""

    @abstractmethod
    def mouse_move_relative(self, dx: int, dy: int) -> None:
        """Move the mouse by (dx, dy) pixels relative to current position."""

    @abstractmethod
    def mouse_set_pos(self, x: int, y: int) -> None:
        """Move the mouse to absolute screen position (x, y)."""

    @abstractmethod
    def mouse_get_pos(self) -> tuple[int, int]:
        """Return current mouse position as (x, y)."""

    # --- Keyboard ---
    @abstractmethod
    def key_event(self, key: str, down: bool) -> None:
        """Fire a key-down or key-up event for the named key."""

    @abstractmethod
    def get_virtual_keycode(self, key: str) -> int:
        """Return the platform virtual-key code for *key*."""


class PathManager(ABC):
    """Abstracts platform paths, permissions, and system configuration."""

    @abstractmethod
    def find_game_launcher_folder(self) -> str:
        """Return the path to the game launcher folder (may be empty string)."""

    @abstractmethod
    def find_game_folder(self) -> str:
        """Return the path to the installed game folder."""

    @abstractmethod
    def enable_dpi_awareness(self) -> None:
        """Enable DPI awareness (Windows) or no-op (macOS)."""

    @abstractmethod
    def is_admin(self) -> bool:
        """Return True if the process has elevated / accessibility permissions."""

    @abstractmethod
    def get_process_name(self) -> str:
        """Return the platform-specific process/bundle name for the game."""
