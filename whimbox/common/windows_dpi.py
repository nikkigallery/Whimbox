import ctypes

from whimbox.common.logger import logger


_dpi_awareness_initialized = False


def enable_dpi_awareness() -> None:
    """Enable DPI awareness early to avoid Windows coordinate virtualization."""
    global _dpi_awareness_initialized

    import sys
    if sys.platform == 'darwin':
        _dpi_awareness_initialized = True
        logger.info("已启用 DPI 感知: MacOS Retina Auto")
        return

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
