"""Constants."""

import threading
import contextvars
from contextlib import contextmanager
from whimbox.common.path_lib import IS_DEV_MODE
from whimbox.config.config import global_config

PAPER_LAUNCHER_NAME = "xstarter.exe"

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
_task_pause_lock = threading.Lock()
_task_can_run = threading.Event()
_task_can_run.set()
_task_resume_generation = 0
_restart_on_resume_generation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    'restart_on_resume_generation', default=None
)


class TaskResumedDuringRestartableOperation(Exception):
    """A paused operation must restart instead of continuing from its old UI state."""


@contextmanager
def restart_operation_on_task_resume():
    """Interrupt only the current task operation after a pause/resume cycle."""
    token = _restart_on_resume_generation.set(task_resume_generation())
    try:
        yield
        wait_for_task_resume()
    finally:
        _restart_on_resume_generation.reset(token)


def reset_task_pause() -> None:
    with _task_pause_lock:
        _task_can_run.set()


def toggle_task_pause() -> bool:
    """Toggle the foreground task; return True when it is now paused."""
    global _task_resume_generation
    with _task_pause_lock:
        if _task_can_run.is_set():
            _task_can_run.clear()
            return True
        _task_resume_generation += 1
        _task_can_run.set()
        return False


def task_resume_generation() -> int:
    with _task_pause_lock:
        return _task_resume_generation


def is_task_paused() -> bool:
    return not _task_can_run.is_set()


def wait_for_task_resume() -> bool:
    """Wait without blocking the stop hotkey. False means the task was stopped."""
    stop_flag = current_stop_flag.get()
    while not _task_can_run.wait(0.1):
        if stop_flag is not None and stop_flag.is_set():
            return False
    if stop_flag is not None and stop_flag.is_set():
        return False
    expected_generation = _restart_on_resume_generation.get()
    if expected_generation is not None and task_resume_generation() != expected_generation:
        raise TaskResumedDuringRestartableOperation()
    return True

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
def get_process_name() -> str:
    from whimbox.platform.factory import get_path_manager
    return get_path_manager().get_process_name()

PROCESS_NAME = get_process_name()


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
