from typing import List, Union

from whimbox.common.utils.asset_utils import get_name_from_caller
from whimbox.common.utils.img_utils import crop
from whimbox.ui.template.img_manager import ImgIcon
from whimbox.ui.template.text_manager import Text
from whimbox.ui.ui_assets import AreaPageTitleFeature

class UIPage():
    parent = None

    def __init__(self, check_icon: Union[ImgIcon, Text, List]):
        self.links = {}
        self.name = get_name_from_caller(depth=2)
        self.check_icon_list = []
        if isinstance(check_icon, List):
            self.check_icon_list = check_icon
        elif isinstance(check_icon, ImgIcon):
            self.check_icon_list.append(check_icon)
        elif isinstance(check_icon, Text):
            self.check_icon_list.append(check_icon)

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        """
        
        button:Button/Str
        """
        self.links[destination] = button

    def is_current_page(self, itt, cap=None):
        for imgicon in self.check_icon_list:
            ret = False
            if isinstance(imgicon, ImgIcon):
                icon_cap = cap
                if cap is not None and imgicon.cap_posi is not None:
                    icon_cap = crop(cap, imgicon.cap_posi)
                ret = itt.get_img_existence(imgicon, cap=icon_cap)
            elif isinstance(imgicon, Text):
                ret = itt.get_text_existence(imgicon)
            if ret:
                return True
        return False

    def add_check_icon(self, check_icon: ImgIcon):
        self.check_icon_list.append(check_icon)

class TitlePage(UIPage):
    def __init__(self, title: str):
        self.name = get_name_from_caller(depth=2)
        self.title = title
        self.links = {}

    def is_current_page(self, itt, cap=None):
        return itt.ocr_single_line(area=AreaPageTitleFeature, hsv_limit=([0, 0, 220], [179, 35, 255])) == self.title

