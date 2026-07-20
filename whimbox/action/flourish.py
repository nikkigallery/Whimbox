from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import *
from whimbox.task.task_template import *
from whimbox.ability.ability import ability_manager
from whimbox.ability.cvar import ABILITY_NAME_FLOURISH

class FlourishTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="FlourishTask")
    
    @register_step("开始芳间巡游")
    def step1(self):
        if not ability_manager.change_ability(ABILITY_NAME_FLOURISH):
            self.update_task_result(status=STATE_TYPE_FAILED, message="切换芳间巡游能力失败")
            return STEP_NAME_FINISH
        itt.right_click()
        time.sleep(4)
        itt.key_press(keybind.KEYBIND_ABILITY_DERIVATION_WORLD_1)
        time.sleep(5)
        itt.right_click()
        time.sleep(4)

    def handle_finally(self):
        pass

if __name__ == "__main__":
    task = FlourishTask(session_id="debug")
    task.task_run()

