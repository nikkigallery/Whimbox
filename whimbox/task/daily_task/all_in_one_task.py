'''朝夕心愿一条龙'''

from whimbox.task.task_template import *
from whimbox.task import daily_task
from whimbox.task.mira_crown_task.mira_crown_task import MiraCrownTask
from whimbox.task.daily_task.cvar import *
from whimbox.task.common_task.start_game_task import StartGameTask
from whimbox.task.common_task.close_game_task import CloseGameTask
from whimbox.task.common_task.change_account_task import ChangeAccountTask
from whimbox.task.common_task.enter_game_task import EnterGameTask
from whimbox.task.macro_task.run_macro_task import RunMacroTask
from whimbox.task.navigation_task.auto_path_task import AutoPathTask
from whimbox.map.detection.cvars import MAP_NAME_HOME, MAP_NAME_MIRALAND, MAP_NAME_UNSUPPORTED
from whimbox.map.convert import convert_GameLoc_to_PngMapPx
from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.common.scripts_manager import scripts_manager
from whimbox.task.daily_task.xinghai_run_task import XinghaiRunTask
from whimbox.ui.page_assets import page_bigmap
from whimbox.ui.ui import ui_control


DEFAULT_STEP_CONFIG = [
    ("step_dig", "step_dig", "美鸭梨挖掘"),
    ("step_home_task", "step_home_task", "家园日常"),
    ("step_weekly_realm", "step2", "每周幻境"),
    ("step_zhaoxi", "step3", "朝夕心愿"),
    ("step_xinghai_run", "step4", "星光结晶收集"),
    ("step_xinghai", "step5", "星海拾光"),
    ("step_mira_crown", "step6", "奇迹之冠巅峰赛"),
    ("step_monthly_pass", "step7", "奇迹之旅"),
]

STEP_RESULT_SUCCESS = "success"
STEP_RESULT_FAILED = "failed"
STEP_RESULT_SKIPPED = "skipped"


class AllInOneTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="all_in_one_task")
        self.is_already_in_game = False
        self.is_in_home = True
        self.default_step_states = {
            key: STEP_RESULT_SKIPPED for key, _, _ in DEFAULT_STEP_CONFIG
        }
        self.has_meteor_today = False
        self.pre_custom_step_results = []
        self.post_custom_step_results = []
        self.change_account_enabled = global_config.get_bool("OneDragon", "change_account", False)
        self.auto_close_game_enabled = global_config.get_bool("OneDragon", "auto_close_game", False)
        self.account_list = []
        self.finished_account_list = []
        self.current_account = ""
        self.account_results = []
        self.default_step_enabled = self._load_default_step_enabled()
        self.pre_custom_steps = self._load_custom_steps("OneDragonPreCustomSteps")
        self.post_custom_steps = self._load_post_custom_steps()
        self._rebuild_step_order()

    def _load_default_step_enabled(self):
        return {
            key: global_config.get_bool("OneDragonDefaultSteps", key, True)
            for key, _, _ in DEFAULT_STEP_CONFIG
        }

    def _load_custom_steps(self, section_name):
        raw_items = global_config.get(section_name, "items", [])
        if not isinstance(raw_items, list):
            return []

        items = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            step_id = str(raw_item.get("id") or "").strip()
            step_type = str(raw_item.get("type") or "").strip()
            if not step_id or step_type not in ("path", "macro"):
                continue
            script_name = str(raw_item.get("script_name") or "").strip()
            if not script_name:
                continue
            items.append(
                {
                    "id": step_id,
                    "enabled": bool(raw_item.get("enabled", True)),
                    "type": step_type,
                    "script_name": script_name,
                }
            )
        return items

    def _load_post_custom_steps(self):
        post_items = self._load_custom_steps("OneDragonPostCustomSteps")
        if post_items:
            return post_items
        if self._load_custom_steps("OneDragonPreCustomSteps"):
            return post_items
        return self._load_custom_steps("OneDragonCustomSteps")

    def _rebuild_step_order(self):
        step_order = ["step_start_game"]

        if self.change_account_enabled:
            step_order.append("step_change_account")
        else:
            step_order.append("step_enter_game")

        if any(step.get("enabled", True) for step in self.pre_custom_steps):
            step_order.append("step_pre_custom_steps")

        if self.default_step_enabled.get("step_dig", True):
            step_order.append("step_dig")

        if self.default_step_enabled.get("step_home_task", True):
            step_order.append("step_home_task")

        later_enabled_keys = [
            key for key, _, _ in DEFAULT_STEP_CONFIG[2:]
            if self.default_step_enabled.get(key, True)
        ]
        if later_enabled_keys:
            # step_order.append("step_check_in_home")
            for key in later_enabled_keys:
                step_order.append(next(step_name for config_key, step_name, _ in DEFAULT_STEP_CONFIG if config_key == key))

        if any(step.get("enabled", True) for step in self.post_custom_steps):
            step_order.append("step_post_custom_steps")

        if self.change_account_enabled:
            step_order.append("step_finish_account")

        step_order.append("step8")

        if self.auto_close_game_enabled:
            step_order.append("step_close_game")
            
        self.step_order = step_order

    def _reset_account_result_state(self):
        self.default_step_states = {
            key: STEP_RESULT_SKIPPED for key, _, _ in DEFAULT_STEP_CONFIG
        }
        self.has_meteor_today = False
        self.pre_custom_step_results = []
        self.post_custom_step_results = []

    def _snapshot_current_account_result(self):
        self.account_results.append(
            {
                "account_name": self.current_account,
                "default_steps": dict(self.default_step_states),
                "has_meteor_today": self.has_meteor_today,
                "pre_custom_steps": [dict(item) for item in self.pre_custom_step_results],
                "post_custom_steps": [dict(item) for item in self.post_custom_step_results],
            }
        )
        self._reset_account_result_state()

    def _set_default_step_result(self, key, task_result):
        status = getattr(task_result, "status", "")
        if status == STATE_TYPE_SUCCESS:
            self.default_step_states[key] = STEP_RESULT_SUCCESS
            # self.log_to_gui(task_result.message)
        elif status == STATE_TYPE_STOP:
            self.default_step_states[key] = STEP_RESULT_SKIPPED
        else:
            self.default_step_states[key] = STEP_RESULT_FAILED
            # self.log_to_gui(task_result.message, is_error=True)

    def _append_custom_step_result(self, result_list, step, status, message=""):
        result_list.append(
            {
                "id": step.get("id", ""),
                "type": step.get("type", ""),
                "script_name": step.get("script_name", ""),
                "status": status,
                "message": message,
            }
        )

    def _get_custom_step_title(self, step):
        step_type = step.get("type")
        script_name = step.get("script_name") or ""
        if step_type == "path":
            return f"执行跑图脚本：{script_name}" if script_name else "执行跑图脚本"
        if step_type == "macro":
            return f"执行宏脚本：{script_name}" if script_name else "执行宏脚本"
        return f"不支持的步骤类型：{step_type}"

    def _run_custom_path(self, script_name):
        path_record = scripts_manager.query_path(path_name=script_name, return_one=True)
        if path_record is None:
            return TaskResult(status=STATE_TYPE_FAILED, message=f"路线\"{script_name}\"不存在")
        return AutoPathTask(self.session_id, path_record=path_record).task_run()

    def _run_custom_macro(self, script_name):
        macro_record = scripts_manager.query_macro(script_name, is_play_music=False, return_one=True)
        if macro_record is None:
            return TaskResult(status=STATE_TYPE_FAILED, message=f"宏\"{script_name}\"不存在")
        return RunMacroTask(self.session_id, macro_filename=macro_record.info.name).task_run()

    def _run_custom_step(self, step):
        step_type = step.get("type")
        if step_type == "path":
            return self._run_custom_path(step.get("script_name", ""))
        if step_type == "macro":
            return self._run_custom_macro(step.get("script_name", ""))
        return TaskResult(status=STATE_TYPE_FAILED, message=f"不支持的步骤类型：{step_type}")

    def _format_default_summary_line(self, key, label):
        status = self.default_step_states.get(key, STEP_RESULT_SKIPPED)
        if status == STEP_RESULT_SUCCESS:
            return f"✅{label}已完成"
        if status == STEP_RESULT_SKIPPED:
            return f"⏭️{label}已跳过"
        return f"❌{label}未完成"

    def _format_custom_summary_line(self, item):
        title = self._get_custom_step_title(item)
        status = item.get("status", STEP_RESULT_SKIPPED)
        message = str(item.get("message") or "").strip()
        if status == STEP_RESULT_SUCCESS:
            return f"✅{title}成功"
        if status == STEP_RESULT_SKIPPED:
            return f"⏭️{title}已跳过"
        if message:
            return f"❌{title}失败：{message}"
        return f"❌{title}失败"

    def _format_account_summary_lines(self, account_result):
        account_name = account_result.get("account_name", 1)
        msg_lines = [f"账号{account_name}："]
        default_steps = account_result.get("default_steps", {})
        for key, _, label in DEFAULT_STEP_CONFIG:
            status = default_steps.get(key, STEP_RESULT_SKIPPED)
            if status == STEP_RESULT_SUCCESS:
                msg_lines.append(f"✅{label}已完成")
            elif status == STEP_RESULT_SKIPPED:
                msg_lines.append(f"⏭️{label}已跳过")
            else:
                msg_lines.append(f"❌{label}未完成")

        if account_result.get("has_meteor_today"):
            msg_lines.append("❗发现今日有巨陨星❗")

        pre_custom_steps = account_result.get("pre_custom_steps", [])
        if pre_custom_steps:
            msg_lines.append("前置步骤：")
            for item in pre_custom_steps:
                msg_lines.append(self._format_custom_summary_line(item))

        post_custom_steps = account_result.get("post_custom_steps", [])
        if post_custom_steps:
            msg_lines.append("后置步骤：")
            for item in post_custom_steps:
                msg_lines.append(self._format_custom_summary_line(item))

        return msg_lines

    def _run_custom_steps(self, steps, result_list):
        for step in steps:
            if not step.get("enabled", True):
                self._append_custom_step_result(result_list, step, STEP_RESULT_SKIPPED)
                continue

            self.log_to_gui(self._get_custom_step_title(step))
            task_result = self._run_custom_step(step)
            status = getattr(task_result, "status", "")
            message = str(getattr(task_result, "message", "") or "")

            if status == STATE_TYPE_SUCCESS:
                self._append_custom_step_result(result_list, step, STEP_RESULT_SUCCESS, message)
                continue

            if status == STATE_TYPE_STOP:
                self._append_custom_step_result(
                    result_list,
                    step,
                    STEP_RESULT_SKIPPED,
                    message or "任务已停止",
                )
                self.update_task_result(status=STATE_TYPE_STOP, message=message or "任务已停止")
                return STEP_NAME_FINISH

            self._append_custom_step_result(result_list, step, STEP_RESULT_FAILED, message)
        return None

    def check_in_home(self):
        if not self.is_in_home:
            return
        self.log_to_gui("检查是否在家园")
        from whimbox.map.map import nikki_map
        if not nikki_map.small_map_init_flag:
            nikki_map.reinit_smallmap()
        if nikki_map.map_name == MAP_NAME_HOME:
            self.log_to_gui("传送到大世界")
            loc = convert_GameLoc_to_PngMapPx([-13172.34765625, -54273.6171875], MAP_NAME_MIRALAND)
            nikki_map.bigmap_tp(loc, MAP_NAME_MIRALAND)
        self.is_in_home = False

    @register_step("自动启动游戏")
    def step_start_game(self):
        start_game_task = StartGameTask(session_id=self.session_id)
        task_result = start_game_task.task_run()
        if task_result.status == STATE_TYPE_SUCCESS:
            _, width, height = HANDLE_OBJ.check_shape()
            logger.info(f"当前游戏分辨率：{width}x{height}")
            if width > 2560 or width < 1920:
                msg = f"❗当前游戏分辨率：{width}x{height}。推荐使用1920x1080或1920x1200或2560x1440或2560x1600分辨率，窗口模式。如遇到bug，请修改游戏分辨率和显示模式后重试"
                self.log_to_gui(msg)
            if task_result.message == "已成功进入游戏":
                self.is_already_in_game = True
        else:
            self.update_task_result(STATE_TYPE_FAILED, task_result.message)
            return STEP_NAME_FINISH

    @ register_step("")
    def step_enter_game(self):
        if self.is_already_in_game:
            return
        enter_game_task = EnterGameTask(session_id=self.session_id)
        task_result = enter_game_task.task_run()
        if task_result.status != STATE_TYPE_SUCCESS:
            self.update_task_result(STATE_TYPE_FAILED, task_result.message)
            return STEP_NAME_FINISH

    @register_step("美鸭梨挖掘")
    def step_dig(self):
        dig_task = daily_task.DigTaskV2(session_id=self.session_id)
        task_result = dig_task.task_run()
        self._set_default_step_result("step_dig", task_result)

    @register_step("开始家园日常")
    def step_home_task(self):
        home_task = AutoPathTask(session_id=self.session_id, path_name="家园日常")
        task_result = home_task.task_run()
        self._set_default_step_result("step_home_task", task_result)

        self.log_to_gui("检测是否有巨陨星")
        ui_control.goto_page(page_bigmap)
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.ui_assets import AreaBigMapMeteorText
        text = itt.ocr_single_line(AreaBigMapMeteorText)
        if "巨陨星" in text:
            self.log_to_gui("今日有巨陨星❗")
            self.has_meteor_today = True

    @register_step("检查周本进度")
    def step2(self):
        weekly_realm_task = daily_task.WeeklyRealmTask(session_id=self.session_id)
        task_result = weekly_realm_task.task_run()
        self._set_default_step_result("step_weekly_realm", task_result)

    @register_step("开始完成朝夕心愿")
    def step3(self):
        zhaoxi_task = daily_task.ZhaoxiTask(session_id=self.session_id)
        task_result = zhaoxi_task.task_run()
        self._set_default_step_result("step_zhaoxi", task_result)

    @register_step("收集星光结晶")
    def step4(self):
        xinghai_run_task = XinghaiRunTask(session_id=self.session_id)
        task_result = xinghai_run_task.task_run()
        self._set_default_step_result("step_xinghai_run", task_result)

    @register_step("开始完成星海拾光")
    def step5(self):
        xinghai_task = daily_task.XinghaiTask(session_id=self.session_id)
        task_result = xinghai_task.task_run()
        self._set_default_step_result("step_xinghai", task_result)

    @register_step("开始完成奇迹之冠巅峰赛")
    def step6(self):
        mira_crown_task = MiraCrownTask(session_id=self.session_id)
        if mira_crown_task.check_mira_crown():
            self.check_in_home()
            task_result = mira_crown_task.task_run()
            self._set_default_step_result("step_mira_crown", task_result)
        else:
            self._set_default_step_result("step_mira_crown", TaskResult(
                status=STATE_TYPE_SUCCESS, message="奇迹之冠巅峰赛已做过，直接跳过"
                ))

    @register_step("领取奇迹之旅奖励")
    def step7(self):
        self.check_in_home()
        monthly_pass_task = daily_task.MonthlyPassTask(session_id=self.session_id)
        task_result = monthly_pass_task.task_run()
        self._set_default_step_result("step_monthly_pass", task_result)

    @register_step("执行前置自定义步骤")
    def step_pre_custom_steps(self):
        return self._run_custom_steps(self.pre_custom_steps, self.pre_custom_step_results)

    @register_step("执行后置自定义步骤")
    def step_post_custom_steps(self):
        return self._run_custom_steps(self.post_custom_steps, self.post_custom_step_results)

    def _quit_to_login(self):
        from whimbox.ui.ui_assets import ButtonExit, TextExitBackLoginButton
        from whimbox.ui.page_assets import page_esc
        from whimbox.common.utils.ui_utils import wait_until_appear_then_click
        ui_control.goto_page(page_esc)
        if wait_until_appear_then_click(ButtonExit):
            time.sleep(0.5)
            if wait_until_appear_then_click(TextExitBackLoginButton):
                return True
        return False

    @register_step("切换账号")
    def step_change_account(self):
        if self.is_already_in_game and len(self.account_list) == 0:
            if not self._quit_to_login():
                self.log_to_gui("返回登录界面失败，只完成当前账号一条龙", is_error=True)
                return

        task_result = ChangeAccountTask(
            session_id=self.session_id,
            account_list=self.account_list,
            finished_account_list=self.finished_account_list
        ).task_run()

        if task_result.status == STATE_TYPE_SUCCESS:
            self.current_account = task_result.data['current_account']
            return
        else:
            self.update_task_result(status=STATE_TYPE_FAILED, message=task_result.message)
            return STEP_NAME_FINISH

    @register_step("当前账号一条龙已完成")
    def step_finish_account(self):
        self.is_in_home = True # 重置是否在家园的状态
        self._snapshot_current_account_result()
        self.finished_account_list.append(self.current_account)
        if len(self.account_list) <= len(self.finished_account_list):
            return "step8"

        self.log_to_gui("返回登录界面，准备切换账号")
        if self._quit_to_login():
            return "step_change_account"
        else:
            return "step8"

    @register_step("一条龙结束")
    def step8(self):
        if self.change_account_enabled:
            msg_lines = ["任务结果如下："]
            for account_result in self.account_results:
                msg_lines.append("================")
                msg_lines.extend(self._format_account_summary_lines(account_result))
            self.update_task_result(
                message="\n".join(msg_lines),
                data=self.account_results,
            )
            return

        msg_lines = ["任务结果如下："]
        for key, _, label in DEFAULT_STEP_CONFIG:
            msg_lines.append(self._format_default_summary_line(key, label))

        if self.has_meteor_today:
            msg_lines.append("❗发现今日有巨陨星❗")

        if self.pre_custom_step_results:
            msg_lines.append("前置步骤：")
            for item in self.pre_custom_step_results:
                msg_lines.append(self._format_custom_summary_line(item))

        if self.post_custom_step_results:
            msg_lines.append("后置步骤：")
            for item in self.post_custom_step_results:
                msg_lines.append(self._format_custom_summary_line(item))

        self.update_task_result(
            message="\n".join(msg_lines),
            data={
                "default_steps": dict(self.default_step_states),
                "has_meteor_today": self.has_meteor_today,
                "pre_custom_steps": list(self.pre_custom_step_results),
                "post_custom_steps": list(self.post_custom_step_results),
            },
        )

    @register_step("关闭游戏")
    def step_close_game(self):
        task_result = CloseGameTask(self.session_id).task_run()
        if task_result.status == STATE_TYPE_STOP:
            self.update_task_result(status=STATE_TYPE_STOP, message=task_result.message or "任务已停止")
            return STEP_NAME_FINISH
        if task_result.status != STATE_TYPE_SUCCESS:
            self.update_task_result(status=STATE_TYPE_FAILED, message=task_result.message or "关闭游戏失败")
            return STEP_NAME_FINISH

    def handle_finally(self):
        # 有可能最后一步是关闭游戏，要额外判断一下避免finally时报错
        if HANDLE_OBJ.is_alive():
            return super().handle_finally()

if __name__ == "__main__":
    task = AllInOneTask(session_id="debug")
    result = task.task_run()
    # print(result.to_dict())
    # task.step_check_in_home()
    # task.step_home_task()
