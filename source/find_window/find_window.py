import win32gui
import time
from source.common.logger import logger

def find_nikki_game_window():
    """查找《无限暖暖》的游戏窗口并自动切换到前台"""
    windows = []
    
    def enum_windows_callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "无限暖暖" in title or "nikki" in title.lower() or " Nikki " in title:
            rect = win32gui.GetWindowRect(hwnd)
            x, y, w, h = rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
            windows.append({
                'hwnd': hwnd,
                'title': title,
                'rect': (x, y, w, h),
                'center': (x + w // 2, y + h // 2)
            })
    
    win32gui.EnumWindows(enum_windows_callback, None)
    
    if not windows:
        logger.warning("未找到《无限暖暖》窗口，请确保游戏已启动。")
        return None
    
    # 切换到第一个找到的窗口
    time.sleep(1)
    win32gui.SetForegroundWindow(windows[0]['hwnd'])
    
    window_info = windows[0]
    x, y, w, h = window_info['rect']
    logger.info(f"找到窗口: '{window_info['title']}，并成功跳转'")
    # logger.info(f"位置: ({x}, {y}), 大小: {w}x{h}") 
    # #可能供后续适配分辨率所需，但这个api获取的分辨率并不准确，暂时不影响跳转窗口功能的使用
    # logger.info(f"中心点: {window_info['center']}")
    
    return window_info