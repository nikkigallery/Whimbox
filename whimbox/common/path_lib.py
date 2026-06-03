"""Cross-platform path constants and game directory helpers.

Specific path resolution (registry keys, macOS app bundle paths) is
delegated to the PathManager from the platform factory.
"""
import os

from whimbox.platform.factory import get_path_manager

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 判断是否在开发模式（存在 dev_mode 文件）
IS_DEV_MODE = os.path.exists(os.path.join(os.getcwd(), 'dev_mode'))

ASSETS_PATH = os.path.join(ROOT_PATH, 'assets')
CONFIG_PATH = os.path.join(os.getcwd(), 'configs')
LOG_PATH = os.path.join(os.getcwd(), 'logs')
SCRIPT_PATH = os.path.join(os.getcwd(), 'scripts')
PLUGINS_PATH = os.path.join(ROOT_PATH, 'plugins')


def find_game_launcher_folder() -> str:
    """Return the game launcher folder path for the current platform."""
    return get_path_manager().find_game_launcher_folder()


def find_game_folder() -> str:
    """Return the installed game folder path for the current platform."""
    return get_path_manager().find_game_folder()


if __name__ == "__main__":
    print(find_game_launcher_folder())
    print(find_game_folder())
