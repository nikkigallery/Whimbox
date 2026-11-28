"""
检查并领取星海日常
"""

from whimbox.task.task_template import *
from whimbox.ui.ui import ui_control
from whimbox.ui.page_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import *
from whimbox.task.daily_task.cvar import *
from whimbox.common.logger import logger
from whimbox.map.map import nikki_map
from whimbox.map.convert import convert_GameLoc_to_PngMapPx
from whimbox.map.detection.cvars import MAP_NAME_STARSEA
from whimbox.task.daily_task.starsea_task.lookbook_like_task import LookbookLikeTask
from whimbox.task.photo_task.daily_photo_task import DailyPhotoTask
from whimbox.task.navigation_task.auto_path_task import AutoPathTask

xhsg_task_info_list = [
    {
        "key_words": ["拍下", "你的存在"],
        "score": 200,
        "priority": 5,
        "task_name": XHSG_TASK_TAKE_PHOTO
    },
    {
        "key_words": ["摆饰"],
        "score": 200,
        "priority": 5,
        "task_name": XHSG_TASK_PLACE_ITEM
    },
    {
        "key_words": ["留声机"],
        "score": 100,
        "priority": 5,
        "task_name": XHSG_TASK_CHANGE_MUSIC
    },
    {
        "key_words": ["聚会频道"],
        "score": 100,
        "priority": 5,
        "task_name": XHSG_TASK_GROUP_CHAT
    },
    {
        "key_words": ["星绘图册", "点赞"],
        "score": 200,
        "priority": 5,
        "task_name": XHSG_TASK_BOOKLOOK_LIKE
    },
    {
        "key_words": ["椰果采摘"],
        "score": 300,
        "priority": 0,
        "task_name": XHSG_TASK_COCO_PICKUP
    },
    {
        "key_words": ["举起椰", "照片"],
        "score": 200,
        "priority": 0,
        "task_name": XHSG_TASK_COCO_PHOTO
    },
    {
        "key_words": ["星愿碎片", "投递"],
        "score": 300,
        "priority": 0,
        "task_name": XHSG_TASK_FRAG_PICKUP
    },
    {
        "key_words": ["星愿碎片", "照片"],
        "score": 200,
        "priority": 0,
        "task_name": XHSG_TASK_FRAG_PHOTO
    },
        {
        "key_words": ["漂流瓶", "查看"],
        "score": 200,
        "priority": 4,
        "task_name": XHSG_TASK_BOTTLE_PICKUP
    },
    {
        "key_words": ["投递", "信笺"],
        "score": 200,
        "priority": 3,
        "task_name": XHSG_TASK_BOTTLE_DELIVERY
    },
    {
        "key_words": ["星愿瓶", "合影"],
        "score": 200,
        "priority": 4,
        "task_name": XHSG_TASK_BOTTLE_PHOTO
    },
    {
        "key_words": ["10个星光结晶"],
        "score": 100,
        "priority": 0,
        "task_name": XHSG_TASK_STAR_PICKUP
    },
    {
        "key_words": ["1次流星"],
        "score": 200,
        "priority": 0,
        "task_name": XHSG_TASK_METEOR
    },
    {
        "key_words": ["星芒之翼", "合影"],
        "score": 200,
        "priority": 4,
        "task_name": XHSG_TASK_PLANE_PHOTO
    },
    {
        "key_words": ["制造", "泡泡"],
        "score": 200,
        "priority": 3,
        "task_name": XHSG_TASK_BUBBLE_MAKE
    },
    {
        "key_words": ["泡泡", "合影"],
        "score": 200,
        "priority": 0,
        "task_name": XHSG_TASK_BUBBLE_PHOTO
    },
    {
        "key_words": ["动物互动", "3次"],
        "score": 300,
        "priority": 5,
        "task_name": XHSG_TASK_TRANS_ANIMAL_THREE
    },
    {
        "key_words": ["不同的动物"],
        "score": 100,
        "priority": 5,
        "task_name": XHSG_TASK_TRANS_ANIMAL_ONE
    },
]

class XinghaiTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="xinghai_task")
        self.current_score = 0

    @register_step("检查星海拾光完成情况")
    def step2(self):
        ui_control.goto_page(page_daily_task)
        try:
            self.current_score = get_daily_score(AreaXhsgScore)
        except:
            self.current_score = 0
        if self.current_score == 500:
            return "step5"
        else:
            self.log_to_gui(f"星海拾光完成度：{self.current_score}/500")
            return

    @register_step("查看星海拾光具体任务")
    def step3(self):
        ui_control.goto_page(page_xhsg)
        itt.delay(1, comment="等待页面稳定")
        itt.wait_until_stable(threshold=0.99)
        def check_task(click_pos):
            itt.move_and_click(click_pos, anchor=ANCHOR_CENTER)
            time.sleep(0.3)
            if not itt.get_img_existence(IconXhsgTaskFinished):
                task_text = itt.ocr_single_line(AreaXhsgTaskText)
                logger.info(f"任务文本：{task_text}")
                for task_info in xhsg_task_info_list:
                    is_match = True
                    for key_word in task_info["key_words"]:
                        if key_word not in task_text:
                            is_match = False
                            break
                    if is_match:
                        return task_info
                return None
            else:
                return None

        # 获得未完成任务列表
        self.unfinished_tasks = []
        for click_pos in XHSG_TASK_CENTERS:
            if self.need_stop():
                break
            unfinished_task = check_task(click_pos)
            if unfinished_task == None:
                continue
            else:
                self.log_to_gui(f"未完成任务：{unfinished_task['task_name']}")
                self.unfinished_tasks.append(unfinished_task)
        
        # 根据优先级和分数排序
        self.unfinished_tasks.sort(
            key=lambda x: (x['priority'], x['score']),
            reverse=True
        )
        back_to_page_main()

    @register_step("开始做星海拾光任务")
    def step4(self):
        task_dict = {
            XHSG_TASK_BOOKLOOK_LIKE: LookbookLikeTask(session_id=self.session_id),
            XHSG_TASK_GROUP_CHAT: AutoPathTask(session_id=self.session_id, path_name="星海拾光_聚会聊天"),
            XHSG_TASK_BUBBLE_MAKE: AutoPathTask(session_id=self.session_id, path_name="星海拾光_制造泡泡"),
            XHSG_TASK_PLACE_ITEM: AutoPathTask(session_id=self.session_id, path_name="星海拾光_放置摆饰"),
            XHSG_TASK_CHANGE_MUSIC: AutoPathTask(session_id=self.session_id, path_name="星海拾光_更改音乐"),
            XHSG_TASK_BOTTLE_PICKUP: AutoPathTask(
                session_id=self.session_id,
                path_name="星海拾光_拾取漂流瓶",
                excepted_num=1,
            ),
            XHSG_TASK_BOTTLE_DELIVERY: AutoPathTask(session_id=self.session_id, path_name="星海拾光_投递漂流瓶"),
            XHSG_TASK_TAKE_PHOTO: DailyPhotoTask(session_id=self.session_id),
            XHSG_TASK_BOTTLE_PHOTO: AutoPathTask(session_id=self.session_id, path_name="星海拾光_合影漂流瓶"),
            XHSG_TASK_TRANS_ANIMAL_ONE: AutoPathTask(session_id=self.session_id, path_name="星海拾光_化身动物"),
            XHSG_TASK_TRANS_ANIMAL_THREE: AutoPathTask(session_id=self.session_id, path_name="星海拾光_化身动物"),
            XHSG_TASK_PLANE_PHOTO: AutoPathTask(session_id=self.session_id, path_name="星海拾光_合影星芒之翼"),
        }
        self.done_task_names = [] 
        for task in self.unfinished_tasks:
            if self.current_score >= 500 or self.need_stop():
                break
            task_name = task['task_name']
            if task_name in task_dict:
                # 如果已经完成变身动物3次任务，则变身动物1次的任务也肯定完成了
                if task_name == XHSG_TASK_TRANS_ANIMAL_ONE and XHSG_TASK_TRANS_ANIMAL_THREE in self.done_task_names:
                    self.current_score += task['score']
                    self.done_task_names.append(task_name)
                    continue
                # 执行任务并加分
                task_obj = task_dict[task_name]
                result = task_obj.task_run()
                if result.status == STATE_TYPE_SUCCESS:
                    self.current_score += task['score']
                    self.done_task_names.append(task_name)
                else:
                    self.log_to_gui(f"任务\"{task_name}\"失败，继续其他任务", is_error=True)
            else:
                self.log_to_gui(f"暂不支持任务\"{task_name}\"，继续其他任务", is_error=True)


    @register_step("领取星海拾光奖励")
    def step5(self):
        ui_control.goto_page(page_daily_task)
        score = get_daily_score(AreaXhsgScore)
        if score != 500:
            self.update_task_result(status=STATE_TYPE_FAILED, message="星海拾光未完成")
        else:
            self.update_task_result(message="星海拾光已完成")
        ui_control.goto_page(page_xhsg)
        itt.delay(1, comment="等待页面稳定")
        itt.wait_until_stable(threshold=0.99)
        get_daily_reward(AreaXhsgRewards)


    @register_step("退出星海拾光")
    def step6(self):
        ui_control.goto_page(page_main)
        self.log_to_gui("传送回无界枢纽挂机")
        map_loc = convert_GameLoc_to_PngMapPx([-35070.57421875, 44421.59765625], MAP_NAME_STARSEA)
        nikki_map.bigmap_tp(map_loc, MAP_NAME_STARSEA)

if __name__ == "__main__":
    xinghai_task = XinghaiTask(session_id="debug")
    # print(xinghai_task.task_run())
    xinghai_task.step2()
