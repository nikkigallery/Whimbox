import os
import sys
import configparser

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 判断是否在开发模式（存在 dev_mode 文件）
IS_DEV_MODE = os.path.exists(os.path.join(os.getcwd(), 'dev_mode'))

ASSETS_PATH = os.path.join(ROOT_PATH, 'assets')
CONFIG_PATH = os.path.join(os.getcwd(), 'configs')
LOG_PATH = os.path.join(os.getcwd(), 'logs')
SCRIPT_PATH = os.path.join(os.getcwd(), 'scripts')
PLUGINS_PATH = os.path.join(ROOT_PATH, 'plugins')

if sys.platform == 'win32':
    import win32api, win32con

def find_game_launcher_folder():
    if sys.platform == 'darwin':
        return "/Applications/Infinity Nikki.app"

    # HKEY_CURRENT_USER\Software\InfinityNikki Launcher
    path = ""
    if sys.platform == 'win32':
        key = 'Software\\InfinityNikki Launcher'
        try:
            key = win32api.RegOpenKey(win32con.HKEY_CURRENT_USER, key, 0, win32con.KEY_READ)
            path, _ = win32api.RegQueryValueEx(key, "")  # 读取默认值
            win32api.RegCloseKey(key)
        except Exception as e:
            path = ""
    
    return path

def find_game_folder():
    if sys.platform == 'darwin':
        return "/Applications/Infinity Nikki.app"

    user_home = os.path.expanduser('~')
    config_path = os.path.join(user_home, 'AppData', 'Local', 'InfinityNikki Launcher', 'config.ini')
    if not os.path.exists(config_path):
        return ""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = configparser.ConfigParser()
        config.read_file(f)
        try:
            return config['Download']['gameDir']
        except (KeyError, configparser.NoSectionError):
            return ""

if __name__ == "__main__":
    print(find_game_launcher_folder())
    print(find_game_folder())
