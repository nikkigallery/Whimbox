"""macOS path utilities and system configuration."""
from __future__ import annotations

from whimbox.core.interfaces import PathManager
from whimbox.common.logger import logger


class MacOSPathManager(PathManager):
    """macOS implementation of PathManager."""

    PROCESS_NAME = 'com.infoldgames.infinitynikkien'
    GAME_APP_PATH = '/Applications/Infinity Nikki.app'

    def find_game_launcher_folder(self) -> str:
        return self.GAME_APP_PATH

    def find_game_folder(self) -> str:
        return self.GAME_APP_PATH

    def enable_dpi_awareness(self) -> None:
        # macOS handles Retina DPI automatically; nothing to do.
        logger.info("已启用 DPI 感知: MacOS Retina Auto")

    def is_admin(self) -> bool:
        # macOS uses Accessibility permissions rather than root/sudo for input injection.
        return True

    def get_process_name(self) -> str:
        return self.PROCESS_NAME
