import multiprocessing
if __name__ == '__main__':
    multiprocessing.freeze_support()

import asyncio
import sys

from whimbox.common.logger import logger
from whimbox.common.windows_dpi import enable_dpi_awareness

def _clear_temp_file():
    logger.info("清理上次运行产生的临时文件")
    import shutil
    import os
    from pathlib import Path
    screenshot_dir = Path(os.getcwd()) / "logs" / "screenshot"
    if screenshot_dir.exists():
        for entry in screenshot_dir.iterdir():
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                continue

def _prepare():
    enable_dpi_awareness()
    from whimbox.common.utils.utils import is_admin
    if not is_admin():
        logger.error("请用管理员权限运行")
        exit()
    from importlib.metadata import PackageNotFoundError, version
    try:
        logger.info(f"奇想盒后台版本号: {version('whimbox')}")
    except PackageNotFoundError:
        logger.info(f"奇想盒后台版本号: dev")
    _clear_temp_file()

def run_whimbox():
    _prepare()

    from whimbox.plugin_runtime import init_plugins
    from whimbox.agent import whimbox_agent
    from whimbox.rpc_server import start_rpc_server

    logger.info("加载插件……")
    init_plugins()
    logger.info("启动agent……")
    asyncio.run(whimbox_agent.start())
    logger.info("启动rpc服务器……")
    asyncio.run(start_rpc_server())

def run_one_dragon():
    _prepare()

    from whimbox.task.daily_task.all_in_one_task import AllInOneTask
    
    logger.info("开始执行一条龙任务...")
    task = AllInOneTask(session_id="default")
    task_result = task.task_run()
    logger.info(f"一条龙任务完成: {task_result.message}")
    logger.info("任务结束，程序退出")

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "startOneDragon":
            run_one_dragon()
        elif sys.argv[1] == "smokeTest":
            _prepare()
            logger.info("Smoke test passed successfully!")
            sys.exit(0)
        else:
            run_whimbox()
    else:
        run_whimbox()

if __name__ == "__main__":
    main()
