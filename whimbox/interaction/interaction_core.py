import inspect
import math
import random
import threading
import time
import cv2
import os
import ctypes

from whimbox.common import path_lib
from whimbox.ui.template import img_manager, text_manager, posi_manager
from whimbox.common.timer_module import TimeoutTimer, AdvanceTimer
from whimbox.common.cvars import *
from whimbox.common.path_lib import ROOT_PATH
from whimbox.common.logger import logger, get_logger_format_date
from whimbox.common.utils.img_utils import crop, process_with_hsv_limit, similar_img, add_padding
from whimbox.config.config import global_config
from whimbox.ui.ui_assets import IconShopFeature, IconGachaFeature
from whimbox.common.utils.asset_utils import AnchorPosi

ocr_type = global_config.get('General', 'ocr')
if ocr_type == 'rapid':
    from whimbox.api.ocr_rapid import ocr
else:
    raise ValueError(f"ocr配置错误：{ocr_type}")

import sys
if sys.platform == 'win32':
    GetDC = ctypes.windll.user32.GetDC
    CreateCompatibleDC = ctypes.windll.gdi32.CreateCompatibleDC
    GetClientRect = ctypes.windll.user32.GetClientRect
    CreateCompatibleBitmap = ctypes.windll.gdi32.CreateCompatibleBitmap
    SelectObject = ctypes.windll.gdi32.SelectObject
    BitBlt = ctypes.windll.gdi32.BitBlt
    SRCCOPY = 0x00CC0020
    GetBitmapBits = ctypes.windll.gdi32.GetBitmapBits
    DeleteObject = ctypes.windll.gdi32.DeleteObject
    ReleaseDC = ctypes.windll.user32.ReleaseDC
    PostMessageW = ctypes.windll.user32.PostMessageW
    MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW


class InteractionBGD:
    """
    thanks for https://zhuanlan.zhihu.com/p/361569101
    """

    def __init__(self, hwnd_handler):
        self.hwnd_handler = hwnd_handler
        logger.info("InteractionBGD created")
        self.WHEEL_DELTA = 120
        self.DEFAULT_DELAY_TIME = 0.05
        self.itt_exec = None
        self.capture_obj = None
        self.operation_lock = threading.Lock()
        import whimbox.interaction.interaction_normal
        self.itt_exec = whimbox.interaction.interaction_normal.InteractionNormal(self.hwnd_handler)
        from whimbox.interaction.capture import PrintWindowCapture
        self.capture_obj = PrintWindowCapture(self.hwnd_handler)


    def capture(self, anchor_posi: AnchorPosi=None, jpgmode=NORMAL_CHANNELS):
        """窗口客户区截图

        Args:
            posi ( AnchorPosi ): 截图区域的坐标, y2>y1,x2>x1. 全屏截图时为None。
            jpgmode(int): 
                0:return jpg (3 channels, delete the alpha channel)
                1:return nikki background channel, background color is black
                2:return nikki ui channel, background color is black

        Returns:
            numpy.ndarray: 图片数组
        """

        ret = self.capture_obj.capture()
        if anchor_posi is not None:
            ret = crop(ret, anchor_posi)
        if ret.shape[2]==3:
            pass
        elif jpgmode == NORMAL_CHANNELS:
            ret = ret[:, :, :3]
        elif jpgmode == FOUR_CHANNELS:
            return ret
        return ret

    def get_screen_center(self):
        resolution = self.capture_obj.resolution
        if resolution:
            x = 1920/2
            y = 1920/2 * resolution[0]/resolution[1]
            print(x, y)
            return(int(x), int(y))
        else:
            return (1920/2, 1080/2)

    def ocr_single_line(self, area: posi_manager.Area, padding=50, hsv_limit=None) -> str:
        cap = self.capture(anchor_posi = area.position)
        if hsv_limit:
            cap = process_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
        if padding:
            cap = add_padding(cap, padding)
        res = ocr.get_all_texts(cap, mode=1)
        return res

    def ocr_multiple_lines(self, area: posi_manager.Area, padding=50, hsv_limit=None) -> list:
        cap = self.capture(anchor_posi = area.position)
        if hsv_limit:
            cap = process_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
        if padding:
            cap = add_padding(cap, padding)
        res = ocr.get_all_texts(cap, mode=0)
        return res

    def ocr_and_detect_posi(self, area: posi_manager.Area, padding=50, hsv_limit=None, cap=None, show_res=False):
        if cap is None:
            cap = self.capture(anchor_posi=area.position)
        else:
            cap = crop(cap, area.position)
        if hsv_limit:
            cap = process_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
        if padding:
            cap = add_padding(cap, padding)
        res = ocr.detect_and_ocr(cap, show_res)
        if padding:
            for text, box in res.items():
                res[text] = [
                    box[0] - padding, 
                    box[1] - padding, 
                    box[2] - padding, 
                    box[3] - padding]
        return res


    # def get_img_position(self, imgicon: img_manager.ImgIcon) -> list:
    #     upper_func_name = inspect.getframeinfo(inspect.currentframe().f_back)[2]
    #     cap = self.capture(posi=imgicon.cap_posi)
    #     matching_rate, max_loc = similar_img(cap, imgicon.image, ret_mode=IMG_POSI)
    #     bbox = Bbox(imgicon.cap_posi[0], imgicon.cap_posi[1], imgicon.cap_posi[0]+max_loc[0], imgicon.cap_posi[1]+max_loc[1])
    #     if imgicon.is_print_log(matching_rate >= imgicon.threshold):
    #         logger.trace('imgname: ' + imgicon.name + 'max_loc: ' + str(max_loc) + ' |function name: ' + upper_func_name)

    #     if matching_rate >= imgicon.threshold:
    #         return bbox
    #     else:
    #         return None


    def get_img_existence(self, imgicon: img_manager.ImgIcon, is_gray=False, ret_mode = IMG_BOOL, show_res = False, cap = None):
        """检测图片是否存在

        Args:
            imgicon (img_manager.ImgIcon): imgicon对象
            is_gray (bool, optional): 是否启用灰度匹配. Defaults to False.
            is_log (bool, optional): 是否打印日志. Defaults to False.

        Returns:
            bool: bool
        """
        upper_func_name = inspect.getframeinfo(inspect.currentframe().f_back)[2]
        if cap is None:
            cap = self.capture(anchor_posi=imgicon.cap_posi)
        if imgicon.hsv_limit is not None:
            cap = process_with_hsv_limit(cap, imgicon.hsv_limit[0], imgicon.hsv_limit[1])
        elif imgicon.gray_limit is not None:
            cap = cv2.cvtColor(cap, cv2.COLOR_BGRA2GRAY)
            _, cap = cv2.threshold(cap, imgicon.gray_limit[0], imgicon.gray_limit[1], cv2.THRESH_BINARY)
        matching_rate = similar_img(cap, imgicon.image, is_gray=is_gray, is_show_res=show_res)

        if imgicon.is_print_log(matching_rate >= imgicon.threshold):
            logger.trace(
                'imgname: ' + imgicon.name + ' matching_rate: ' + str(
                    matching_rate) + ' |function name: ' + upper_func_name)

        if ret_mode == IMG_BOOLRATE:
            if matching_rate >= imgicon.threshold:
                return matching_rate
            else:
                return False
        elif ret_mode == IMG_RATE:
            return matching_rate
        elif ret_mode == IMG_POSI:
            if matching_rate >= imgicon.threshold:
                return imgicon.cap_center_position_xy
            else:
                return None
        else:
            return matching_rate >= imgicon.threshold


    def get_text_existence(self, textobj: text_manager.TextTemplate, ret_mode=IMG_BOOL, cap=None):
        if cap == None:
            cap = self.capture(anchor_posi=textobj.cap_area.position)
        cap = add_padding(cap, 50)
        res = ocr.get_all_texts(cap)
        is_exist = textobj.match_results(res)
        if textobj.is_print_log(is_exist):
            logger.trace(f"get_text_existence: text: {textobj.text} {'Found' if is_exist else 'Not Found'}")
        if ret_mode==IMG_POSI:
            if is_exist:
                return textobj.cap_area.center_position()
            else:
                return None
        else:
            return is_exist


    def appear(self, obj):
        if isinstance(obj, text_manager.TextTemplate):
            return self.get_text_existence(obj)
        elif isinstance(obj, img_manager.ImgIcon): # Button is also an Icon
            return self.get_img_existence(obj)


    def appear_then_click(self, inputvar, is_gray=False, key_name="left_mouse"):
        """appear then click

        Args:
            inputvar (img_manager.ImgIcon/text_manager.TextTemplate/button_manager.Button)
            is_gray (bool, optional): 是否启用灰度匹配. Defaults to False.
            key_name (str, optional): 按键名称. Defaults to "left_mouse".
            
        Returns:
            bool: bool,点击操作是否成功
        """
        
        upper_func_name = inspect.getframeinfo(inspect.currentframe().f_back)[2]
        match_position = None

        if isinstance(inputvar, img_manager.ImgIcon):
            match_position = self.get_img_existence(inputvar, is_gray=is_gray, ret_mode=IMG_POSI)
            anchor = inputvar.cap_posi.anchor
            
        elif isinstance(inputvar, text_manager.TextTemplate):
            match_position = self.get_text_existence(inputvar, ret_mode=IMG_POSI)
            anchor = inputvar.cap_area.anchor
        
        if match_position:
            logger.trace(f"appear then click: True: {inputvar.name} func: {upper_func_name}")
            if key_name == "left_mouse":
                self.move_and_click(match_position, anchor=anchor)
            elif key_name == "right_mouse":
                self.move_and_click(match_position, anchor=anchor, type='right')
            else:
                self.key_press(key_name)
            return True
        else:
            return False
                

    def wait_until_stable(self, threshold = 0.9995, timeout = 5):
        timeout_timer = TimeoutTimer(timeout)
        last_cap = self.capture()

        pt = time.time()
        t = AdvanceTimer(0.25, 3).start()
        while 1:
            time.sleep(0.1)
            if timeout_timer.istimeout():
                logger.warning("TIMEOUT")
                break
            curr_img = self.capture()
            simi = similar_img(last_cap, curr_img)# abs((last_cap.astype(int)-curr_img.astype(int))).sum()
            if simi > threshold:
                pass
            else:
                t.reset()
            if t.reached():
                if DEBUG_MODE: print('wait time: ', time.time()-pt)
                break
            last_cap = curr_img.copy()


    def delay(self, x, randtime=False, is_log=True, comment=''):
        """延迟一段时间，单位为秒

        Args:
            x : 延迟时间/key words
            randtime (bool, optional): 是否启用加入随机秒. Defaults to True.
            is_log (bool, optional): 是否打印日志. Defaults to True.
            comment (str, optional): 日志注释. Defaults to ''.
        """
        if x  == "animation":
            time.sleep(0.3)
            return
        if x  == "2animation":
            time.sleep(0.6)
            return
        upper_func_name = inspect.getframeinfo(inspect.currentframe().f_back)[2]
        a = random.randint(-10, 10)
        if randtime:
            a = a * x * 0.02
            if x > 0.2 and is_log:
                logger.debug('delay: ' + str(x) + ' rand: ' +
                             str(x + a) + ' |function name: ' + upper_func_name + ' |comment: ' + comment)
            time.sleep(x + a)
        else:
            if x > 0.2 and is_log:
                logger.debug('delay: ' + str(x) + ' |function name: ' + upper_func_name + ' |comment: ' + comment)
            time.sleep(x)

    def _can_interact(self, func_name: str):
        # 判断是否在商城和抽卡界面，在的话禁止操作
        if func_name in ["left_click", "left_down", "left_double_click", "move_and_click"]:
            if self.get_img_existence(IconShopFeature) or self.get_img_existence(IconGachaFeature):
                return False
        return True

    @staticmethod
    def before_operation(print_log=False):
        """装饰器方法：在操作前进行检查"""
        def outwrapper(func):
            def wrapper(self, *args, **kwargs):
                if print_log:
                    func_name = inspect.getframeinfo(inspect.currentframe().f_back)[2]
                    func_name_2 = inspect.getframeinfo(inspect.currentframe().f_back.f_back)[2]
                    logger.trace(f" operation: {func.__name__} | args: {args} | {kwargs} | function name: {func_name} & {func_name_2}")
                
                if not self._can_interact(func.__name__):
                    raise Exception("中断操作：误入商城和抽卡界面")
                
                if not self.hwnd_handler.is_foreground():
                    # stop_flag = get_current_stop_flag()
                    # while True:
                    #     if stop_flag.is_set():
                    #         return None
                    #     if self.hwnd_handler.is_foreground():
                    #         logger.info("恢复操作")
                    #         break
                    #     logger.info(f"前台窗口不是目标窗口，操作暂停 {str(5 - (time.time()%5))} 秒")
                    #     time.sleep(5 - (time.time()%5))
                    self.hwnd_handler.set_foreground()
                    logger.info("游戏窗口丢失焦点，已强制恢复")
                return func(self, *args, **kwargs)
            return wrapper
        return outwrapper

    @before_operation()
    def left_click(self):
        """左键点击"""
        self.itt_exec.left_click()

    @before_operation()
    def left_down(self):
        """左键按下"""
        self.itt_exec.left_down()

    @before_operation()
    def left_up(self):
        """左键抬起"""
        self.itt_exec.left_up()

    @before_operation()
    def left_double_click(self, dt=0.05):
        """左键双击

        Args:
            dt (float, optional): 间隔时间. Defaults to 0.05.
        """
        self.itt_exec.left_double_click(dt=dt)

    @before_operation()
    def right_down(self):
        """右键按下"""
        self.itt_exec.right_down()

    @before_operation()
    def right_up(self):
        """右键抬起"""
        self.itt_exec.right_up()

    @before_operation()
    def right_click(self):
        """右键单击"""
        self.itt_exec.right_click()

    @before_operation()
    def middle_click(self):
        """点击鼠标中键"""
        self.itt_exec.middle_click()
    
    @before_operation()
    def middle_scroll(self, distance):
        """滚动鼠标中键"""
        self.operation_lock.acquire()
        self.itt_exec.middle_scroll(distance)
        self.operation_lock.release()

    @before_operation()
    def key_down(self, key):
        """按下按键

        Args:
            key (str): 按键代号。查阅vkCode.py
        """
        if key == "mouse_left":
            self.itt_exec.left_down()
        elif key == "mouse_right":
            self.itt_exec.right_down()
        elif key == "mouse_middle":
            self.itt_exec.middle_down()
        else:
            self.itt_exec.key_down(key)

    @before_operation()
    def key_up(self, key):
        """松开按键

        Args:
            key (str): 按键代号。查阅vkCode.py
        """
        if key == "mouse_left":
            self.itt_exec.left_up()
        elif key == "mouse_right":
            self.itt_exec.right_up()
        elif key == "mouse_middle":
            self.itt_exec.middle_up()
        else:
            self.itt_exec.key_up(key)

    @before_operation()
    def key_press(self, key):
        """点击按键

        Args:
            key (str): 按键代号。查阅vkCode.py
        """
        if key == "mouse_left":
            self.itt_exec.left_click()
        elif key == "mouse_right":
            self.itt_exec.right_click()
        elif key == "mouse_middle":
            self.itt_exec.middle_click()
        else:
            self.itt_exec.key_press(key)

    @before_operation(print_log=False)
    def move_to(self, position, anchor=ANCHOR_TOP_LEFT, relative=False, smooth=False, smooth_duration=0.2):
        """移动鼠标到坐标

        Args:
            position (list): 坐标
            relative (bool): 是否为相对移动。
        """
        self.operation_lock.acquire()
        self.itt_exec.move_to(
            int(position[0]), 
            int(position[1]),
            resolution=self.capture_obj.resolution,
            anchor=anchor,
            relative=relative,
            smooth=smooth,
            smooth_duration=smooth_duration)
        self.operation_lock.release()


    @before_operation()
    def move_and_click(self, position, anchor=ANCHOR_TOP_LEFT, type='left', delay=0.3):
        """移动鼠标到坐标并点击

        Args:
            position (list): 坐标
            type (str, optional): 点击类型。 Defaults to 'left'.
            delay (float, optional): 延迟时间. Defaults to 0.2.
        """
        self.operation_lock.acquire()
        self.itt_exec.move_to(
            int(position[0]), 
            int(position[1]), 
            resolution=self.capture_obj.resolution,
            anchor=anchor,
            relative=False)
        self.operation_lock.release()
        time.sleep(delay)

        if type == 'left':
            self.itt_exec.left_click()
        elif type == 'right':
            self.itt_exec.right_click()
        elif type == 'middle':
            self.itt_exec.middle_click()
        
            
    def save_snapshot(self, reason:str = ''):
        img = self.capture()
        img_path = os.path.join(path_lib.LOG_PATH, f"{time.time()}.jpg")
        # img_path = os.path.join(ROOT_PATH, "Logs", get_logger_format_date(), f"{reason} | {time.strftime('%H-%M-%S', time.localtime())}.jpg")
        logger.warning(f"Snapshot saved to {img_path}")
        cv2.imwrite(img_path, img)        

from whimbox.common.handle_lib import HANDLE_OBJ
itt = InteractionBGD(HANDLE_OBJ)


if __name__ == '__main__':
    pass
