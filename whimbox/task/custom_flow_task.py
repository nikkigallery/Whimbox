from whimbox.common.custom_flow import get_custom_flow_items
from whimbox.common.scripts_manager import scripts_manager
from whimbox.task.macro_task.run_macro_task import RunMacroTask
from whimbox.task.navigation_task.auto_path_task import AutoPathTask
from whimbox.task.task_template import (
    STATE_TYPE_FAILED,
    STATE_TYPE_STOP,
    STATE_TYPE_SUCCESS,
    STEP_NAME_FINISH,
    TaskResult,
    TaskTemplate,
    register_step,
)


class CustomFlowTask(TaskTemplate):
    def __init__(self, session_id, flow_id=None):
        super().__init__(session_id=session_id, name="custom_flow_task")
        self.items = self._load_items(flow_id)

    @staticmethod
    def _load_items(flow_id=None):
        items = []
        for raw_item in get_custom_flow_items(flow_id):
            if not isinstance(raw_item, dict):
                continue
            step_type = str(raw_item.get("type") or "").strip()
            script_name = str(raw_item.get("script_name") or "").strip()
            if step_type not in ("path", "macro") or not script_name:
                continue
            items.append(
                {
                    "id": str(raw_item.get("id") or "").strip(),
                    "enabled": bool(raw_item.get("enabled", True)),
                    "type": step_type,
                    "script_name": script_name,
                }
            )
        return items

    def _run_item(self, item):
        script_name = item["script_name"]
        if item["type"] == "path":
            path_record = scripts_manager.query_path(
                path_name=script_name,
                return_one=True,
            )
            if path_record is None:
                return TaskResult(
                    status=STATE_TYPE_FAILED,
                    message=f'路线"{script_name}"不存在',
                )
            return AutoPathTask(
                self.session_id,
                path_record=path_record,
            ).task_run()

        macro_record = scripts_manager.query_macro(
            script_name,
            is_play_music=False,
            return_one=True,
        )
        if macro_record is None:
            return TaskResult(
                status=STATE_TYPE_FAILED,
                message=f'宏"{script_name}"不存在',
            )
        return RunMacroTask(
            self.session_id,
            macro_filename=macro_record.info.name,
        ).task_run()

    @staticmethod
    def _item_title(item):
        label = "跑图脚本" if item["type"] == "path" else "宏脚本"
        return f'{label}：{item["script_name"]}'

    @register_step("执行自定义流程")
    def step_run_flow(self):
        enabled_items = [item for item in self.items if item["enabled"]]
        if not enabled_items:
            self.update_task_result(
                status=STATE_TYPE_FAILED,
                message="请至少启用一个有效的自定义流程步骤",
            )
            return STEP_NAME_FINISH

        result_lines = []
        has_failed = False
        for item in enabled_items:
            title = self._item_title(item)
            self.log_to_gui(f"执行{title}")
            task_result = self._run_item(item)
            status = getattr(task_result, "status", "")
            message = str(getattr(task_result, "message", "") or "").strip()

            if status == STATE_TYPE_STOP:
                self.update_task_result(
                    status=STATE_TYPE_STOP,
                    message=message or "任务已停止",
                )
                return STEP_NAME_FINISH

            if status == STATE_TYPE_SUCCESS:
                result_lines.append(f"✅{title}已完成")
            else:
                has_failed = True
                suffix = f"：{message}" if message else ""
                result_lines.append(f"❌{title}执行失败{suffix}")

        self.update_task_result(
            status=STATE_TYPE_FAILED if has_failed else STATE_TYPE_SUCCESS,
            message="\n".join(result_lines),
            data={"items": enabled_items},
        )


if __name__ == "__main__":
    task = CustomFlowTask(session_id="debug")
    print(task.task_run())
