'''通用的游戏UI操作工具'''

from whimbox.ui.template.img_manager import GameImg, ImgIcon
from whimbox.ui.template.button_manager import Button
from whimbox.ui.template.text_manager import Text
from whimbox.ui.template.posi_manager import Area
from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.img_utils import *
from whimbox.common.utils.posi_utils import *
from whimbox.ui.ui_assets import *
from whimbox.common.keybind import keybind
from whimbox.common.cvars import get_current_stop_flag
import time
from whimbox.common.logger import logger


def find_game_img(game_img: GameImg, cap, threshold, scale=0.5, count=1):
    # 准备需要匹配的两张图片
    template = game_img.raw_image
    if template.shape[2] == 4:
        template_rgb = template[:, :, :3]
        alpha = template[:, :, 3]
        mask = (alpha > 128).astype(np.uint8) * 255  # 透明区域设为0，不参与检测
    else:
        template_rgb = template
        mask = None

    if scale:
        # 为什么INTER_LINEAR，因为如果用INTER_NEAREST，有些图片里太细的线条就会被忽略（比如纯真丝线），导致相似度大幅下降
        template_rgb = cv2.resize(template_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        if mask is not None:
            mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    if CV_DEBUG_MODE:
        # 将template_rgb的mask区域显示为黑色，用cv2显示出来
        template_show = template_rgb.copy()
        template_show[mask == 0] = 0
        cv2.imshow("template", template_show)
        cv2.waitKey(0)
    
    # 模板匹配
    res = cv2.matchTemplate(cap, template_rgb, cv2.TM_CCOEFF_NORMED, mask=mask)

    th, tw = template_rgb.shape[:2]

    # 如果只需要找一个目标，使用原有逻辑
    if count == 1:
        # 找到最大匹配位置
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        top_left = max_loc
        bottom_right = (top_left[0] + tw, top_left[1] + th)

        if max_val >= threshold:
            logger.trace('imgname: ' + game_img.name + ' matching_rate: ' + str(max_val))

        if CV_DEBUG_MODE:
            # 在目标图上绘制矩形
            print(f"max_val: {max_val}, threshold: {threshold}")
            cap_copy = cap.copy()
            cv2.rectangle(cap_copy, top_left, bottom_right, (0,255,0), 3)
            cv2.imshow("Detected", cap_copy)
            cv2.waitKey(0)
        
        if max_val < threshold:
            return None

        box = [top_left[0], top_left[1], bottom_right[0], bottom_right[1]]
        return box
    
    # 如果需要找多个目标，使用非极大值抑制
    else:
        # 找到所有超过阈值的位置
        loc = np.where(res >= threshold)
        
        if len(loc[0]) == 0:
            return None
        
        # 将位置和相似度组合
        matches = []
        for pt in zip(*loc[::-1]):  # loc[::-1]将(y,x)转换为(x,y)
            matches.append({
                'x': pt[0],
                'y': pt[1],
                'score': res[pt[1], pt[0]]
            })
        
        # 按相似度降序排序
        matches.sort(key=lambda x: x['score'], reverse=True)
        
        # 使用非极大值抑制来过滤重叠的检测框
        boxes = []
        for match in matches:
            x, y = match['x'], match['y']
            box = [x, y, x + tw, y + th]
            
            # 检查是否与已有的框重叠
            is_overlap = False
            for existing_box in boxes:
                # 计算重叠区域
                x1 = max(box[0], existing_box[0])
                y1 = max(box[1], existing_box[1])
                x2 = min(box[2], existing_box[2])
                y2 = min(box[3], existing_box[3])
                
                if x1 < x2 and y1 < y2:
                    # 有重叠，计算重叠面积占比
                    overlap_area = (x2 - x1) * (y2 - y1)
                    box_area = (box[2] - box[0]) * (box[3] - box[1])
                    overlap_ratio = overlap_area / box_area
                    
                    # 如果重叠超过50%，认为是同一个目标
                    if overlap_ratio > 0.5:
                        is_overlap = True
                        break
            
            if not is_overlap:
                boxes.append(box)
                logger.trace(f'imgname: {game_img.name} matching_rate: {match["score"]:.4f}')
                
                # 如果已经找到足够数量的目标，停止搜索
                if len(boxes) >= count:
                    break
        
        if CV_DEBUG_MODE:
            # 在目标图上绘制所有找到的矩形
            cap_copy = cap.copy()
            for i, box in enumerate(boxes):
                cv2.rectangle(cap_copy, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 3)
                cv2.putText(cap_copy, str(i+1), (box[0], box[1]-5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.imshow("Detected Multiple", cap_copy)
            cv2.waitKey(0)
        
        return boxes


def scroll_find_click(area: Area, target, threshold=0, hsv_limit=None, scale=0, str_match_mode=0, click_offset=(0, 0), need_scroll=True, scroll_distance=15) -> bool:
    '''
    在指定的区域内滚动，寻找并点击目标

    Args:
        area: 目标区域
        target: 寻找的目标，ImgIcon或GameImg或str
        threshold: 相似度阈值, 用于ImgIcon和GameImg
        hsv_limit: hsv上下限，用于ImgIcon和str，如([0, 0, 230], [180, 60, 255])
        scale: target的缩放比例，用于ImgIcon或GameImg
        str_match_mode: 字符串匹配模式，0为完全匹配，1为包含匹配
        click_offset: 点击偏移量，tuple(x, y)
        need_scroll: 是否需要滚动，默认True
        scroll_disatance: 一次滚动距离，默认15
    
    Returns:
        bool: 是否找到目标
    '''
    box = None
    cap = itt.capture(anchor_posi = area.position)
    is_first_time = True
    while True:
        stop_flag = get_current_stop_flag()
        if stop_flag.is_set():
            return False
        if isinstance(target, ImgIcon):
            target_img = target.image
            if target.hsv_limit:
                hsv_limit = target.hsv_limit
            if hsv_limit:
                if scale:
                    target_img = cv2.resize(target_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                if not target.hsv_limit:
                    target_img = target_img[:, :, 0]
                cap_hsv = process_with_hsv_limit(cap, hsv_limit[0], hsv_limit[1])
                rate, loc = similar_img(cap_hsv, target_img, ret_mode=IMG_RECT)
            else:
                if scale:
                    target_img = cv2.resize(target_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                rate, loc = similar_img(cap, target_img, ret_mode=IMG_RECT)

            if target.is_print_log(rate >= threshold):
                logger.trace('imgname: ' + target.name + ' matching_rate: ' + str(rate))

            if rate > threshold:
                th, tw = target_img.shape[:2]
                top_left = loc
                bottom_right = (top_left[0] + tw, top_left[1] + th)
                if CV_DEBUG_MODE:
                    print(f"rate: {rate}, threshold: {threshold}")
                    cap_copy = cap.copy()
                    cv2.rectangle(cap_copy, top_left, bottom_right, (0, 255, 0), 2)
                    cv2.imshow("Detected", cap_copy)
                    cv2.waitKey(0)
                box = [top_left[0], top_left[1], bottom_right[0], bottom_right[1]]
                break

        elif isinstance(target, GameImg):
            box = find_game_img(target, cap, threshold, scale)
            if box:
                break
        
        elif isinstance(target, str):
            text_box_dict = itt.ocr_and_detect_posi(area, hsv_limit=hsv_limit)
            if str_match_mode == 0:
                if target in text_box_dict:
                    box = text_box_dict[target]
                    break
            elif str_match_mode == 1:
                for text, text_box in text_box_dict.items():
                    if target in text:
                        box = text_box
                        break
                if box is not None:
                    break
        
        else:
            raise Exception(f"不支持的target类型: {type(target)}")


        if need_scroll:
            # 如果第一次没找到目标，就先把画面滚到顶，再开始寻找
            if is_first_time:
                logger.info(f"第一次没找到目标，先把画面滚到顶")
                cap = scroll_to_top(area)
                is_first_time = False
            else:
                # 如果没找到目标，就把鼠标移到area的右下角，向下滚动
                # todo: 支持expand，不过暂时没什么关系
                scroll_posi = (area.position.x2, area.position.y2)
                itt.move_to(scroll_posi, anchor=area.position.anchor)
                itt.middle_scroll(-scroll_distance)
                time.sleep(0.2)

                # 如果画面不再变化，说明滚到底了
                new_cap = itt.capture(anchor_posi = area.position)
                rate = similar_img(cap, new_cap)
                if rate > 0.99:
                    break
                else:
                    cap = new_cap
        else:
            break
        
    if box:
        time.sleep(0.3)
        area.click(target_box=box, offset=click_offset)
        return True
    else:
        return False


def scroll_to_top(area: Area):
    # 鼠标移到area的右下角
    # todo: 支持expand，不过暂时没什么关系
    scroll_posi = (area.position.x2, area.position.y2)
    itt.move_to(scroll_posi, anchor=area.position.anchor)
    last_cap = itt.capture(anchor_posi=area.position)
    while True:
        stop_flag = get_current_stop_flag()
        if stop_flag.is_set():
            return last_cap
        itt.middle_scroll(15)
        time.sleep(0.2)
        new_cap = itt.capture(anchor_posi=area.position)
        rate = similar_img(last_cap, new_cap)
        if rate > 0.99:
            return new_cap
        last_cap = new_cap

    
def wait_until_appear_then_click(obj, retry_time=3):
    while retry_time > 0:
        stop_flag = get_current_stop_flag()
        if stop_flag.is_set():
            return False
        if isinstance(obj, Button):
            if itt.appear_then_click(obj):
                return True
        elif isinstance(obj, Text):
            if itt.appear_then_click(obj):
                return True
        else:
            return False
        retry_time -= 1
        if retry_time > 0:
            time.sleep(1)
    return False


def wait_until_appear(obj, area=None, retry_time=3):
    while retry_time > 0:
        stop_flag = get_current_stop_flag()
        if stop_flag.is_set():
            return False
        if area:
            cap = itt.capture(anchor_posi=area.position)
        else:
            cap = None
        if isinstance(obj, ImgIcon):
            if itt.get_img_existence(obj, cap=cap):
                return True
        elif isinstance(obj, Text):
            if itt.get_text_existence(obj, cap=cap):
                return True
        else:
            return False
        retry_time -= 1
        if retry_time > 0:
            time.sleep(1)
    return False


def back_to_page_main(timeout=15.0, max_esc=8):
    # 让UI返回到主界面
    stop_flag = get_current_stop_flag()
    deadline = time.monotonic() + timeout
    esc_count = 0
    while not stop_flag.is_set():
        if time.monotonic() >= deadline or esc_count >= max_esc:
            logger.warning(
                f"Timed out returning to the main page; stopping Esc loop "
                f"(timeout={timeout:.1f}s, esc_count={esc_count})"
            )
            return False

        itt.wait_until_stable(threshold=0.95)
        if itt.get_img_existence(IconDungeonFeature):
            itt.key_press(keybind.KEYBIND_BACK)
            itt.delay(0.5)
            wait_until_appear_then_click(ButtonDungeonQuitOK, retry_time=1)
        elif itt.get_img_existence(IconPageMainFeature):
            return True
        else:
            itt.key_press('esc')
            esc_count += 1
            itt.delay(0.35, is_log=False)

    return False

def skip_to_page_main():
    # 采集时，如果遇到没有的东西，会自动弹出获取窗口，不断按f跳过直到回到主界面
    stop_flag = get_current_stop_flag()
    while not stop_flag.is_set():
        time.sleep(0.5)
        if itt.get_img_existence(IconSkip) or itt.get_img_existence(IconClickSkip):
            itt.key_press(keybind.KEYBIND_INTERACTION)
        if itt.get_img_existence(IconPageMainFeature):
            break

def skip_dialog():
    stop_flag = get_current_stop_flag()
    while not stop_flag.is_set():
        time.sleep(0.5)
        if itt.get_img_existence(IconSkipDialog):
            itt.key_press(keybind.KEYBIND_INTERACTION)
        else:
            # 防止遇到什么奇怪的情况，退出前再做一次检查
            time.sleep(0.5)
            if not itt.get_img_existence(IconSkipDialog):
                break
            else:
                itt.key_press(keybind.KEYBIND_INTERACTION)

def skip_get_award():
    if wait_until_appear(IconClickSkip):
        itt.delay(1, comment="不加延迟，有些电脑就是不行")
        itt.key_press(keybind.KEYBIND_INTERACTION)
        return True
    else:
        return False
        

def get_daily_score(area:Area):
    try:
        score_str = itt.ocr_single_line(area, hsv_limit=([0, 0, 250], [0, 0, 255]))
        score = int(score_str.strip())
        if score % 100 != 0:
            raise Exception(f"分数识别异常:{score_str}")
        else:
            return score
    except:
        raise Exception(f"分数识别异常:{score_str}")

def get_daily_reward(area:Area):
    cap = itt.capture(area.position)
    lower = [0, 0, 125]
    upper = [30, 255, 255]
    cap_hsv = process_with_hsv_limit(cap, lower, upper)
    circles = cv2.HoughCircles(
        cap_hsv,
        cv2.HOUGH_GRADIENT,
        dp=1,          # 累加器分辨率（可调 1.0~1.5）
        minDist=100,      # 圆心最小间距，建议≈ 2*minRadius - 些许
        param1=60,      # Canny高阈值
        param2=8,       # 累加器阈值，越小越容易出圆（可调 8~18）
        minRadius=30,
        maxRadius=35
    )
    target_circle = None
    if circles is not None:
        for x, y, r in circles[0, :]:
            if not target_circle:
                target_circle = (x, y, r)
                break

    if CV_DEBUG_MODE and target_circle:
        x, y, r = np.uint16(np.around(target_circle))
        new_cap = cap.copy()
        cv2.circle(new_cap, (x, y), r, (0, 0, 255), 2)
        cv2.circle(new_cap, (x, y), 2, (0, 0, 255), 3)
        cv2.imshow("target_reward", new_cap)
        cv2.waitKey(0)

    if target_circle:
        x, y, r = target_circle
        target_box = (x-r, y-r, x+r, y+r)
        area.click(target_box)
        skip_get_award()
        return True
    else:
        return False



if __name__ == "__main__":
    # while True:
    #     print(itt.get_img_existence(IconDungeonFeature, ret_mode=IMG_RATE))
    #     time.sleep(1)
    # back_to_page_main()
    CV_DEBUG_MODE = True
    from whimbox.ui.material_icon_assets import material_icon_dict
    # material_name = "纯真丝线"
    material_name = "扣扣毛球"
    target = material_icon_dict[material_name]["icon"]
    # scroll_find_click(AreaBigMapMaterialSelect, target, threshold=0.8, scale=0.45)
    # cap = itt.capture(posi=AreaDigItemSelect.position)
    # find_game_img(target, cap, threshold=0.7, scale=0.46)
    # cap = itt.capture(posi=AreaBigMapMaterialSelect.position)
    # find_game_img(target, cap, threshold=0.9, scale=0.45)
    scroll_find_click(AreaJihuaCostSelect, target, threshold=0.70, scale=0.5)
    # cap = itt.capture(AreaJihuaCostSelect.position)
    # find_game_img(target, cap, threshold=0.73, scale=0.5)

    # hsv_limit = [np.array([0, 0, 100]), np.array([180, 60, 255])]
    # # scroll_find_click(AreaDigMainTypeSelect, IconMaterialTypeMonster, threshold=0.85, hsv_limit=hsv_limit, scale=1.233)
    # scroll_find_click(AreaDigSubTypeSelect, IconMaterialTypeInsect, threshold=0.85, hsv_limit=hsv_limit, scale=0.83)

    # scroll_find_click(AreaBlessHuanjingLevelsSelect, "翻滚", str_match_mode=1)
    # scroll_find_click(AreaEscEntrances, "美鸭梨挖掘")
    # cap = cv2.imread(r"D:\workspaces\python\Whimbox\tools\snapshot\1768526354.406669.png")
    # print(find_game_img(GameImgStarCrystal, cap, threshold=0.70, scale=1, count=3))
    
    # print(get_daily_reward(AreaXhsgRewards))
