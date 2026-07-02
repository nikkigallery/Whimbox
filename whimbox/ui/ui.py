from whimbox.common.cvars import *
from whimbox.common.timer_module import AdvanceTimer
from whimbox.interaction.interaction_core import itt
from whimbox.ui.page_assets import *
from whimbox.ui.template.button_manager import Button
from whimbox.common.keybind import KeybindRef
from whimbox.common.logger import logger
from whimbox.ui.page import TitlePage
from whimbox.common.utils.ui_utils import back_to_page_main
from whimbox.common.cvars import get_current_stop_flag

from threading import Lock

class UI():

    def __init__(self) -> None:
        self.switch_ui_lock = Lock()

    def ui_additional(self, timeout=None):
        """
        Handle all annoying popups during UI switching.
        """
        timer = None
        if timeout:
            timer = AdvanceTimer(timeout)
            timer.start()
        stop_flag = get_current_stop_flag()
        while page_loading.is_current_page(itt) and not stop_flag.is_set():
            itt.delay(1, comment='game is loading...')
            if timer and timer.reached():
                logger.warning("UI loading timeout")
                break

    def is_valid_page(self):
        try:
            self.get_current_page()
            return True
        except Exception as e:
            return False

    def get_current_page(self):
        ret_page = None
        title_text = itt.ocr_single_line(area=AreaPageTitleFeature, hsv_limit=([0, 0, 220], [179, 35, 255]))
        for page in ui_page_dict.values():
            if isinstance(page, TitlePage):
                if page.title == title_text:
                    ret_page = page
                    break
            else:
                if page.is_current_page(itt):
                    ret_page = page
                    break
        if not ret_page:
            raise Exception("无法识别当前页面")
        else:
            return ret_page

    def verify_page(self, page: UIPage) -> bool:
        return page.is_current_page(itt)

    def goto_page(self, target_page: UIPage, retry_times=0, max_retry=1):
        from collections import deque
        try:
            self.switch_ui_lock.acquire()
            
            logger.info(f"Goto page: {target_page}")
            
            # Get current page
            try:
                current_page = self.get_current_page()
            except Exception as e:
                logger.warning(f"Cannot recognize current page, going back to main page: {e}")
                back_to_page_main()
                current_page = page_main
            
            # Check if already at destination
            if current_page == target_page:
                logger.debug(f'Already at destination page: {target_page}')
                self.switch_ui_lock.release()
                return
            
            # Use BFS to find path from current page to target page
            queue = deque([(current_page, [current_page])])
            visited = {current_page}
            path = None
            
            while queue:
                page, current_path = queue.popleft()
                
                # Check all links from this page
                for next_page, button in page.links.items():
                    if next_page in visited:
                        continue
                    
                    visited.add(next_page)
                    new_path = current_path + [next_page]
                    
                    if next_page == target_page:
                        path = new_path
                        break
                    
                    queue.append((next_page, new_path))
                
                if path:
                    break
            
            # If no path found, raise exception
            if not path:
                error_msg = f"No path found from {current_page} to {target_page}"
                logger.error(error_msg)
                self.switch_ui_lock.release()
                raise Exception(error_msg)
            
            # Log the complete path
            path_str = " -> ".join([str(p) for p in path])
            logger.info(f"Navigation path: {path_str}")
            
            # Execute the path step by step
            success = True
            stop_flag = get_current_stop_flag()
            for i in range(len(path) - 1):
                if stop_flag.is_set():
                    self.switch_ui_lock.release()
                    return 
                from_page = path[i]
                to_page = path[i + 1]
                button = from_page.links.get(to_page, None)
                
                if button is None:
                    error_msg = f"No button found to go from {from_page} to {to_page}"
                    logger.error(error_msg)
                    self.switch_ui_lock.release()
                    raise Exception(error_msg)
                
                logger.debug(f'Page switch: {from_page} -> {to_page}')
                
                # Click the button
                if isinstance(button, KeybindRef):
                    button = button.resolve()

                if isinstance(button, str):
                    itt.key_press(button)
                elif isinstance(button, Button):
                    if not itt.appear_then_click(button):
                        logger.warning(f"未找到按钮：{button.name}")
                        success = False
                        break
                elif isinstance(button, Text):
                    if not itt.appear_then_click(button):
                        logger.warning(f"未找到按钮：{button.text}")
                        success = False
                        break

                itt.wait_until_stable(threshold=0.98)
                # Handle loading screen
                self.ui_additional()
                logger.info("page transition completed")
                
                # 移动鼠标到左上角，避免触发某些UI的悬停样式，导致特征识别失败
                itt.move_to((0, 0))

                # Verify we reached the expected page
                if not to_page.is_current_page(itt):
                    logger.warning(f"Expected to be at {to_page}, but verification failed. Retrying...")
                    success = False
                    break

            if not success:
                self.switch_ui_lock.release()
                if retry_times >= max_retry:
                    page_name = target_page.name
                    for ch_name, page in ui_page_dict.items():
                        if page.name == target_page.name:
                            page_name = ch_name

                    err_msg = f"前往页面 「{page_name}」 失败"
                    if page_name == "能力配置":
                        err_msg = f"前往页面 「{page_name} 」失败，请先确保接了“变强吧大喵”任务。接取该任务后，换装界面将更新成最新版"
                    raise Exception(err_msg)
                else:
                    back_to_page_main()
                    self.goto_page(target_page, retry_times=retry_times + 1, max_retry=max_retry)
            else:
                logger.info(f"Successfully arrived at {target_page}")
                self.switch_ui_lock.release()
            
        except Exception as e:
            logger.error(f"goto_page failed: {e}")
            if self.switch_ui_lock.locked():
                self.switch_ui_lock.release()
            raise e

    def ensure_page(self, page: UIPage):
        if not self.verify_page(page):
            self.goto_page(page)


ui_control = UI()

if __name__ == '__main__':
    # ui_control.goto_page(page_esc)
    # ui_control.goto_page(page_huanjing_jihua)
    ui_control.goto_page(page_ability)
