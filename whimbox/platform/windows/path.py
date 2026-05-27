"""Windows path and system utilities."""
from __future__ import annotations

import ctypes
import configparser
import os

import win32api
import win32con

from whimbox.core.interfaces import PathManager
from whimbox.common.logger import logger


class WindowsPathManager(PathManager):
    """Windows implementation of PathManager."""

    PROCESS_NAME = 'X6Game-Win64-Shipping.exe'

    def find_game_launcher_folder(self) -> str:
        key_path = 'Software\\InfinityNikki Launcher'
        try:
            key = win32api.RegOpenKey(win32con.HKEY_CURRENT_USER, key_path, 0, win32con.KEY_READ)
            path, _ = win32api.RegQueryValueEx(key, '')
            win32api.RegCloseKey(key)
            return path
        except Exception:
            return ''

    def find_game_folder(self) -> str:
        user_home = os.path.expanduser('~')
        config_path = os.path.join(
            user_home, 'AppData', 'Local', 'InfinityNikki Launcher', 'config.ini'
        )
        if not os.path.exists(config_path):
            return ''
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            return config['Download']['gameDir']
        except (KeyError, configparser.NoSectionError):
            return ''

    def enable_dpi_awareness(self) -> None:
        from whimbox.common.windows_dpi import _enable_dpi_win32
        _enable_dpi_win32()

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception as exc:
            logger.error(f'检查管理员权限失败: {exc}')
            return False

    def get_process_name(self) -> str:
        return self.PROCESS_NAME
