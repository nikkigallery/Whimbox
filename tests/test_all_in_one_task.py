import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.task.daily_task.all_in_one_task import AllInOneTask
from whimbox.task.task_template import STATE_TYPE_FAILED, STATE_TYPE_SUCCESS, STEP_NAME_FINISH


class AllInOneTaskCloseTest(unittest.TestCase):
    def _make_task(self, finish_actions=None):
        task = object.__new__(AllInOneTask)
        task.session_id = "test-session"
        task.finish_actions = set(finish_actions or [])
        task.update_task_result = Mock()
        return task

    @patch("whimbox.task.daily_task.all_in_one_task.emit_event")
    @patch("whimbox.task.daily_task.all_in_one_task.CloseGameTask")
    def test_selected_finish_actions_close_game_and_request_app_quit(self, close_game_task, emit_event):
        close_game_task.return_value.task_run.return_value = SimpleNamespace(
            status=STATE_TYPE_SUCCESS,
            message="",
        )
        task = self._make_task(["关闭游戏", "关闭奇想盒"])

        result = task.step_finish_actions()

        self.assertIsNone(result)
        emit_event.assert_called_once_with(
            "event.app.finish_actions",
            {
                "reason": "one_dragon_completed",
                "session_id": "test-session",
                "quit_app": True,
                "shutdown_computer": False,
            },
        )
        task.update_task_result.assert_not_called()

    @patch("whimbox.task.daily_task.all_in_one_task.emit_event")
    @patch("whimbox.task.daily_task.all_in_one_task.CloseGameTask")
    def test_close_game_failure_does_not_quit_app(self, close_game_task, emit_event):
        close_game_task.return_value.task_run.return_value = SimpleNamespace(
            status=STATE_TYPE_FAILED,
            message="关闭失败",
        )
        task = self._make_task(["关闭游戏", "关闭奇想盒", "关机"])

        result = task.step_finish_actions()

        self.assertEqual(STEP_NAME_FINISH, result)
        emit_event.assert_not_called()
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_FAILED,
            message="关闭失败",
        )

    @patch("whimbox.task.daily_task.all_in_one_task.emit_event")
    @patch("whimbox.task.daily_task.all_in_one_task.CloseGameTask")
    def test_shutdown_without_close_game_skips_close_task(self, close_game_task, emit_event):
        task = self._make_task(["关机"])

        result = task.step_finish_actions()

        self.assertIsNone(result)
        close_game_task.assert_not_called()
        emit_event.assert_called_once_with(
            "event.app.finish_actions",
            {
                "reason": "one_dragon_completed",
                "session_id": "test-session",
                "quit_app": False,
                "shutdown_computer": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
