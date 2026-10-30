from whimbox.task.task_template import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import*
from whimbox.ui.ui_assets import *

class PickupBottleTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="pickup_bottle_task")
        self.material_count_dict = {"漂流瓶": 0}
    
    @register_step("拾取漂流瓶")
    def step1(self):
        if not wait_until_appear(IconPickupFeature, area=AreaPickup, retry_time=2):
            self.update_task_result(status=STATE_TYPE_FAILED, message="未找到漂流瓶")
            return STEP_NAME_FINISH
        itt.key_press(keybind.KEYBIND_INTERACTION)
        if wait_until_appear_then_click(ButtonXhsgBottleClose):
            self.material_count_dict["漂流瓶"] += 1
        self.update_task_result(
            message=f"拾取漂流瓶x{self.material_count_dict["漂流瓶"]}",
            data=self.material_count_dict
        )


if __name__ == "__main__":
    task = PickupBottleTask(session_id="debug")
    print(task.task_run())