from source.mcp_server import start_mcp_server
from source.mcp_agent import start_agent
from source.ingame_ui.ingame_ui import run_ingame_ui
import asyncio
import threading

def main():
    threading.Thread(target=start_mcp_server).start()
    asyncio.run(start_agent())
    run_ingame_ui()


if __name__ == '__main__':
    main()
    # test