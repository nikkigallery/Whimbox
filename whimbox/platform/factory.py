"""Platform factory — returns the correct manager implementation for the running OS.

All sys.platform checks in the Python backend are centralised here.
No other module should import sys and check sys.platform.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from whimbox.core.interfaces import CaptureManager, InputManager, PathManager, WindowManager


@lru_cache(maxsize=1)
def get_window_manager() -> WindowManager:
    """Return the singleton WindowManager for the current platform."""
    if sys.platform == 'win32':
        from whimbox.platform.windows.window import WindowsWindowManager
        return WindowsWindowManager()
    elif sys.platform == 'darwin':
        from whimbox.platform.macos.window import MacOSWindowManager
        return MacOSWindowManager()
    else:
        raise RuntimeError(f'Unsupported platform: {sys.platform}')


@lru_cache(maxsize=1)
def get_capture_manager() -> CaptureManager:
    """Return the singleton CaptureManager for the current platform."""
    if sys.platform == 'win32':
        from whimbox.platform.windows.capture import WindowsCaptureManager
        return WindowsCaptureManager()
    elif sys.platform == 'darwin':
        from whimbox.platform.macos.capture import MacOSCaptureManager
        return MacOSCaptureManager()
    else:
        raise RuntimeError(f'Unsupported platform: {sys.platform}')


@lru_cache(maxsize=1)
def get_input_manager() -> InputManager:
    """Return the singleton InputManager for the current platform."""
    if sys.platform == 'win32':
        from whimbox.platform.windows.input import WindowsInputManager
        return WindowsInputManager()
    elif sys.platform == 'darwin':
        from whimbox.platform.macos.input import MacOSInputManager
        return MacOSInputManager()
    else:
        raise RuntimeError(f'Unsupported platform: {sys.platform}')


@lru_cache(maxsize=1)
def get_path_manager() -> PathManager:
    """Return the singleton PathManager for the current platform."""
    if sys.platform == 'win32':
        from whimbox.platform.windows.path import WindowsPathManager
        return WindowsPathManager()
    elif sys.platform == 'darwin':
        from whimbox.platform.macos.path import MacOSPathManager
        return MacOSPathManager()
    else:
        raise RuntimeError(f'Unsupported platform: {sys.platform}')
