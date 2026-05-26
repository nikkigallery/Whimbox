import os
import inspect
import linecache
import numpy as np

from whimbox.common.errors import *
from whimbox.common.utils.utils import load_json
from whimbox.common.path_lib import ASSETS_PATH
from whimbox.common.cvars import *
from whimbox.common.utils.posi_utils import area_center

ASSETS_INDEX_JSON = load_json("imgs_index.json", f"{ASSETS_PATH}/imgs")

def get_name(x):
    (filename, line_number, function_name, text) = x
    # = traceback.extract_stack()[-2]
    return text[:text.find('=')].strip()


def get_name_from_caller(depth=2):
    frame = inspect.currentframe()
    for _ in range(depth):
        if frame is None:
            break
        frame = frame.f_back
    if frame is None:
        return "unknown_asset"
    line = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
    if "=" in line:
        return line.split("=", 1)[0].strip()
    return f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno}"

class AnchorPosi():
    def __init__(self, x1, y1, x2, y2, anchor=ANCHOR_TOP_LEFT, expand=False):
        self.x1 = int(x1)
        self.y1 = int(y1)
        self.x2 = int(x2)
        self.y2 = int(y2)
        self.anchor = anchor
        self.expand = expand
    
    def get_center(self):
        return [(self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2]
    
    def trans_inner_box_posi(self, target_box_posi):
        if isinstance(target_box_posi, AnchorPosi):
            return AnchorPosi(self.x1 + target_box_posi.x1, self.y1 + target_box_posi.y1, self.x1 + target_box_posi.x2, self.y1 + target_box_posi.y2)
        else:
            return AnchorPosi(self.x1 + target_box_posi[0], self.y1 + target_box_posi[1], self.x1 + target_box_posi[2], self.y1 + target_box_posi[3])
    
    def trans_inner_point_posi(self, target_point_posi):
        return (self.x1 + target_point_posi[0], self.y1 + target_point_posi[1])
    
    def click(self, target_box=None, offset=(0, 0)):
        from whimbox.interaction.interaction_core import itt
        if target_box is None:
            center = self.get_center()
        else:
            center = area_center(target_box)
            center = self.trans_inner_point_posi(center)
        center = (center[0] + offset[0], center[1] + offset[1])
        itt.move_and_click(center, anchor=self.anchor)


def asset_get_bbox(image, anchor=ANCHOR_TOP_LEFT, expand=False, black_offset=15) -> AnchorPosi:
    """
    A numpy implementation of the getbbox() in pillow.完全低于阈值返回None
    Args:
        image (np.ndarray): Screenshot.
        anchor (str): 锚点类型. Defaults to ANCHOR_TOP_LEFT.
        expand (bool): 是否在垂直方向上扩展. Defaults to False.
    Returns:
        AnchorPosi: AnchorPosi object
    """
    channel = image.shape[2] if len(image.shape) == 3 else 0
    if channel == 3:
        image = np.max(image, axis=2)
    x = np.where(np.max(image, axis=0) > black_offset)[0]
    y = np.where(np.max(image, axis=1) > black_offset)[0]
    if x.size == 0 or y.size == 0:
        return None
    return AnchorPosi(x[0], y[0], x[-1] + 1, y[-1] + 1, anchor, expand)


class AssetBase():
    def __init__(self, name: str, print_log:int=LOG_NONE) -> None:
        if name is None:
            raise NAME_NOT_FOUND
        self.name = name
        self.print_log = print_log

    def get_img_path(self):
        if self.name in ASSETS_INDEX_JSON:
            rel_path = ASSETS_INDEX_JSON[self.name]['rel_path']
            rel_path = rel_path.replace('\\', os.sep)
            return os.path.join(ASSETS_PATH, rel_path)
        r = self.search_path(self.name)
        if r != None:
            return r
        else:
            raise IMG_NOT_FOUND(self.name)

    def search_path(self, filename) -> str:
        for comp_filename in [filename + '.png', filename + '.jpg']:
            folder_path = os.path.join(ASSETS_PATH)
            for root, dirs, files in os.walk(folder_path):
                if comp_filename in files:
                    return os.path.abspath(os.path.join(root, comp_filename))

    def is_print_log(self, b: bool):
        if b:
            if self.print_log == LOG_WHEN_TRUE or self.print_log == LOG_ALL:
                return True
            else:
                return False
        else:
            if self.print_log == LOG_WHEN_FALSE or self.print_log == LOG_ALL:
                return True
            else:
                return False
