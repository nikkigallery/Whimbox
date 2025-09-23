from source.common.utils.utils import is_admin
from source.common.logger import logger
if not is_admin():
    logger.error("请用管理员权限运行")
    exit()

from source.mcp_server import start_mcp_server
from source.mcp_agent import start_agent
from source.ingame_ui.ingame_ui import run_ingame_ui
from source.find_window.find_window import find_nikki_game_window

import asyncio
import threading

def main():
    find_nikki_game_window()# 查找游戏窗口并前台运行游戏
    threading.Thread(target=start_mcp_server).start()
    asyncio.run(start_agent())
    run_ingame_ui()


if __name__ == '__main__':
    main()