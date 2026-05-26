"""Constants."""

import threading
import contextvars
from whimbox.common.path_lib import IS_DEV_MODE
from whimbox.config.config import global_config

DEBUG_MODE = global_config.get_bool('General', 'debug') and IS_DEV_MODE
CV_DEBUG_MODE = global_config.get_bool('General', 'cv_debug') and IS_DEV_MODE

RPC_CONFIG = {
    "host": "127.0.0.1",
    "port": 8350,
}

# 使用 contextvars 来存储当前任务的 stop_flag
# 这样每个任务都有独立的 stop_flag，无需在每个函数中显式传递
current_stop_flag: contextvars.ContextVar[threading.Event] = contextvars.ContextVar(
    'current_stop_flag', 
    default=None
)

# 当前会话 ID（用于日志/状态透传）
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_session_id',
    default="default",
)

# 当前运行 ID（用于统一 run.status / run.log 关联）
current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_run_id',
    default="",
)

def get_current_stop_flag() -> threading.Event:
    """获取当前上下文的 stop_flag
    
    如果当前上下文没有设置 stop_flag，返回一个永远不会被设置的 flag
    这样可以保证代码在没有 task 上下文时也能正常运行
    """
    flag = current_stop_flag.get()
    if flag is None:
        # 如果没有设置，创建一个永远不会被设置的 flag
        flag = threading.Event()
    return flag


def get_current_session_id() -> str:
    """获取当前上下文的 session_id"""
    return current_session_id.get() or "default"


def get_current_run_id() -> str:
    """获取当前上下文的 run_id"""
    return current_run_id.get() or ""

# 全局前台任务运行标志（用于后台任务判断是否有前台任务在运行）
_foreground_task_running = False
_foreground_task_lock = threading.Lock()

def set_foreground_task_running(running: bool):
    """设置前台任务运行状态"""
    global _foreground_task_running
    with _foreground_task_lock:
        _foreground_task_running = running

def has_foreground_task() -> bool:
    """检查是否有前台任务在运行"""
    global _foreground_task_running
    with _foreground_task_lock:
        return _foreground_task_running

# Angle modes
ANGLE_NORMAL = 0
ANGLE_NEGATIVE_Y = 1
ANGLE_NEGATIVE_X = 2
ANGLE_NEGATIVE_XY = 3

# Process name
PROCESS_NAME = None  # Resolved lazily via get_path_manager().get_process_name()


# log
LOG_NONE = 0
LOG_WHEN_TRUE = 1
LOG_WHEN_FALSE = 2
LOG_ALL = 3

IMG_RATE = 0
IMG_POSI = 1
IMG_POINT = 2
IMG_RECT = 3
IMG_BOOL = 4
IMG_BOOLRATE = 5

NORMAL_CHANNELS = 0
FOUR_CHANNELS = 40000

THREAD_PAUSE_SET_FLAG_ONLY = 0
THREAD_PAUSE_FORCE_TERMINATE = 1

# 字符串匹配模式
CONTAIN_MATCHING = 0
ACCURATE_MATCHING = 1

ANCHOR_TOP_LEFT = 'TOP_LEFT'
ANCHOR_TOP_RIGHT = 'TOP_RIGHT'
ANCHOR_BOTTOM_LEFT = 'BOTTOM_LEFT'
ANCHOR_BOTTOM_RIGHT = 'BOTTOM_RIGHT'
ANCHOR_CENTER ='CENTER'
ANCHOR_TOP_CENTER = 'TOP_CENTER'
ANCHOR_BOTTOM_CENTER = 'BOTTOM_CENTER'
ANCHOR_LEFT_CENTER = 'LEFT_CENTER'
ANCHOR_RIGHT_CENTER = 'RIGHT_CENTER'
ANCHOR_NONE = 'NONE'
