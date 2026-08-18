from whimbox.interaction.interaction_core import itt
from whimbox.common.utils.ui_utils import *
from whimbox.task.task_template import *
from whimbox.ability.ability import ability_manager
from whimbox.ability.cvar import ABILITY_NAME_MACHINE

# infuse 注入
# extract 抽取

class MachineTask(TaskTemplate):
    def __init__(self, session_id, mode):
        super().__init__(session_id=session_id, name="MachineTask")
        self.target_mode = mode
    
    @register_step("开始机械控制")
    def step1(self):
        if not ability_manager.change_ability(ABILITY_NAME_MACHINE):
            self.update_task_result(status=STATE_TYPE_FAILED, message="切换械控能力失败")
            return STEP_NAME_FINISH
        
        current_mode = None
        if ability_manager.check_current_ability(IconAbilityMachineInfuse):
            current_mode = "infuse"
            self.log_to_gui("当前为注入模式")
        elif ability_manager.check_current_ability(IconAbilityMachineExtract):
            current_mode = "extract"
            self.log_to_gui("当前为抽取模式")
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message="无法识别当前械控模式")
            return STEP_NAME_FINISH
        
        if self.target_mode != current_mode:
            self.log_to_gui("切换械控模式")
            itt.key_press(keybind.KEYBIND_ABILITY_DERIVATION_WORLD_1)
            itt.delay(1, comment="等待切换完成")
            
        itt.right_click()
        time.sleep(1)

    def handle_finally(self):
        pass

if __name__ == "__main__":
    ability_manager.init_need_ability([ABILITY_NAME_MACHINE])
    task = MachineTask(session_id="debug", mode="extract")
    print(task.task_run())

