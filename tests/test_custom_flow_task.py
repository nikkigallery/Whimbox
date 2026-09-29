import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.task.custom_flow_task import CustomFlowTask
from whimbox.task.task_template import (
    STATE_TYPE_FAILED,
    STATE_TYPE_STOP,
    STATE_TYPE_SUCCESS,
    STEP_NAME_FINISH,
)


class CustomFlowTaskTests(unittest.TestCase):
    def _make_task(self, items):
        task = object.__new__(CustomFlowTask)
        task.items = items
        task.log_to_gui = Mock()
        task.update_task_result = Mock()
        task._run_item = Mock()
        return task

    def test_runs_enabled_items_in_order_and_skips_disabled_items(self):
        items = [
            {"id": "1", "enabled": True, "type": "path", "script_name": "路线A"},
            {"id": "2", "enabled": False, "type": "macro", "script_name": "宏B"},
            {"id": "3", "enabled": True, "type": "macro", "script_name": "宏C"},
        ]
        task = self._make_task(items)
        task._run_item.side_effect = [
            SimpleNamespace(status=STATE_TYPE_SUCCESS, message=""),
            SimpleNamespace(status=STATE_TYPE_SUCCESS, message=""),
        ]

        result = task.step_run_flow()

        self.assertIsNone(result)
        self.assertEqual(
            [items[0], items[2]],
            [call.args[0] for call in task._run_item.call_args_list],
        )
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_SUCCESS,
            message="✅跑图脚本：路线A已完成\n✅宏脚本：宏C已完成",
            data={"items": [items[0], items[2]]},
        )

    def test_failed_item_does_not_prevent_later_items_from_running(self):
        items = [
            {"id": "1", "enabled": True, "type": "path", "script_name": "路线A"},
            {"id": "2", "enabled": True, "type": "macro", "script_name": "宏B"},
        ]
        task = self._make_task(items)
        task._run_item.side_effect = [
            SimpleNamespace(status=STATE_TYPE_FAILED, message="失败原因"),
            SimpleNamespace(status=STATE_TYPE_SUCCESS, message=""),
        ]

        result = task.step_run_flow()

        self.assertIsNone(result)
        self.assertEqual(2, task._run_item.call_count)
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_FAILED,
            message="❌跑图脚本：路线A执行失败：失败原因\n✅宏脚本：宏B已完成",
            data={"items": items},
        )

    def test_stop_result_ends_flow_immediately(self):
        items = [
            {"id": "1", "enabled": True, "type": "path", "script_name": "路线A"},
            {"id": "2", "enabled": True, "type": "macro", "script_name": "宏B"},
        ]
        task = self._make_task(items)
        task._run_item.return_value = SimpleNamespace(
            status=STATE_TYPE_STOP,
            message="用户停止",
        )

        result = task.step_run_flow()

        self.assertEqual(STEP_NAME_FINISH, result)
        task._run_item.assert_called_once_with(items[0])
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_STOP,
            message="用户停止",
        )

    @patch("whimbox.task.custom_flow_task.get_custom_flow_items")
    def test_load_items_filters_invalid_entries(self, get_custom_flow_items):
        get_custom_flow_items.return_value = [
            {"id": "1", "enabled": True, "type": "path", "script_name": "路线A"},
            {"id": "2", "enabled": True, "type": "music", "script_name": "乐谱B"},
            {"id": "3", "enabled": True, "type": "macro", "script_name": ""},
            "invalid",
        ]

        self.assertEqual(
            [{"id": "1", "enabled": True, "type": "path", "script_name": "路线A"}],
            CustomFlowTask._load_items(),
        )

    @patch("whimbox.task.custom_flow_task.get_custom_flow_items")
    def test_load_items_uses_requested_flow(self, get_custom_flow_items):
        get_custom_flow_items.return_value = []

        CustomFlowTask._load_items("flow-2")

        get_custom_flow_items.assert_called_once_with("flow-2")


if __name__ == "__main__":
    unittest.main()
