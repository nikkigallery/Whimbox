from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import *
from whimbox.task.task_template import *
from whimbox.ability.ability import ability_manager
from whimbox.ability.cvar import ABILITY_NAME_INSECT

class FloralInsectTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="FloralInsectTask")
    
    @register_step("开始花套捕虫")
    def step1(self):
        if not ability_manager.change_ability(ABILITY_NAME_INSECT):
            self.update_task_result(status=STATE_TYPE_FAILED, message="切换捕虫能力失败")
            return STEP_NAME_FINISH
        itt.right_click()
        time.sleep(1)

    def handle_finally(self):
        pass

if __name__ == "__main__":
    task = FloralInsectTask(session_id="debug")
    task.task_run()

