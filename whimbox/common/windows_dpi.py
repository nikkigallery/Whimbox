"""DPI awareness helper.

On Windows, calls the PathManager to enable per-monitor DPI awareness.
On macOS, this is a no-op — the PathManager handles it transparently.
"""
import ctypes

from whimbox.common.logger import logger


_dpi_awareness_initialized = False


def _enable_dpi_win32() -> None:
    """Windows-only implementation, called by WindowsPathManager.enable_dpi_awareness()."""
    global _dpi_awareness_initialized

    if _dpi_awareness_initialized:
        return

    user32 = ctypes.windll.user32

    # Prefer per-monitor v2 for accurate client rects on scaled displays.
    try:
        dpi_context_per_monitor_v2 = ctypes.c_void_p(-4)
        if user32.SetProcessDpiAwarenessContext(dpi_context_per_monitor_v2):
            _dpi_awareness_initialized = True
            logger.info("已启用 DPI 感知: Per-Monitor V2")
            return
    except Exception:
        pass

    try:
        shcore = ctypes.windll.shcore
        process_per_monitor_dpi_aware = 2
        result = shcore.SetProcessDpiAwareness(process_per_monitor_dpi_aware)
        if result in (0, 0x00000005):
            _dpi_awareness_initialized = True
            logger.info("已启用 DPI 感知: Per-Monitor")
            return
    except Exception:
        pass

    try:
        if user32.SetProcessDPIAware():
            _dpi_awareness_initialized = True
            logger.info("已启用 DPI 感知: System")
            return
    except Exception:
        pass

    logger.warning("未能启用 DPI 感知，截图可能受系统缩放影响")


def enable_dpi_awareness() -> None:
    """Enable DPI awareness early to avoid Windows coordinate virtualisation.

    Delegates to the platform PathManager so that macOS receives a no-op.
    """
    from whimbox.platform.factory import get_path_manager
    get_path_manager().enable_dpi_awareness()
