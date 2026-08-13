import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.task.daily_task.all_in_one_task import AllInOneTask
from whimbox.task.task_template import STATE_TYPE_FAILED, STATE_TYPE_SUCCESS, STEP_NAME_FINISH


class AllInOneTaskCloseTest(unittest.TestCase):
    def _make_task(self):
        task = object.__new__(AllInOneTask)
        task.session_id = "test-session"
        task.update_task_result = Mock()
        return task

    @patch("whimbox.task.daily_task.all_in_one_task.emit_event")
    @patch("whimbox.task.daily_task.all_in_one_task.CloseGameTask")
    def test_close_game_success_requests_app_quit(self, close_game_task, emit_event):
        close_game_task.return_value.task_run.return_value = SimpleNamespace(
            status=STATE_TYPE_SUCCESS,
            message="",
        )
        task = self._make_task()

        result = task.step_close_game()

        self.assertIsNone(result)
        emit_event.assert_called_once_with(
            "event.app.quit",
            {
                "reason": "one_dragon_completed",
                "session_id": "test-session",
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
        task = self._make_task()

        result = task.step_close_game()

        self.assertEqual(STEP_NAME_FINISH, result)
        emit_event.assert_not_called()
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_FAILED,
            message="关闭失败",
        )


if __name__ == "__main__":
    unittest.main()
