from whimbox.common.utils.ui_utils import back_to_page_main
from whimbox.task.task_template import TaskTemplate, register_step
import time
from whimbox.common.logger import logger
from whimbox.ui.ui import ui_control

class TestTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="test_task")
        self.count = 0

    @register_step("测试步骤")
    def step1(self):
        while not self.need_stop():
            logger.info(f"测试步骤，第{self.count}次")
            self.count += 1
            time.sleep(5)

if __name__ == "__main__":
    import cv2
    from whimbox.common.path_lib import *
    from whimbox.interaction.interaction_core import itt
    from whimbox.common.utils.img_utils import *
    from whimbox.ui.ui_assets import *
    from whimbox.common.cvars import IMG_RATE
    from whimbox.common.utils import ui_utils
    from whimbox.ui.page_assets import *
    # cap = cv2.imread(os.path.join(ROOT_PATH, "..", "tools", "snapshot", "bug", "bug2.png"))
    # cap = cv2.resize(cap, (1920, 1080))
    # cap = crop(cap, ButtonItemExpiredConfirm.cap_posi)
    # print(itt.get_img_existence(ButtonItemExpiredConfirm, cap=cap, ret_mode=IMG_RATE, show_res=True))
    while True:
        print(itt.get_img_existence(ButtonItemPlaceableItem, ret_mode=IMG_RATE, show_res=True))
        # cv2.imshow("cap", itt.capture(AreaBlessHuanjingDifficulty3.position))
        # cv2.waitKey(1)
        time.sleep(0.5)
    # ui_control.goto_page(page_huanjing_bless)


