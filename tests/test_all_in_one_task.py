import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.task.daily_task.all_in_one_task import (
    DEFAULT_STEP_CONFIG,
    STEP_RESULT_SKIPPED,
    AllInOneTask,
)
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
    def test_selected_finish_actions_close_game_and_request_app_quit(
        self, close_game_task, emit_event
    ):
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
    def test_close_game_failure_does_not_quit_app(
        self, close_game_task, emit_event
    ):
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
    def test_shutdown_without_close_game_skips_close_task(
        self, close_game_task, emit_event
    ):
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


class AllInOneTaskBlessSparkleTest(unittest.TestCase):
    def _make_task(self):
        task = object.__new__(AllInOneTask)
        task.session_id = "test-session"
        task.default_step_states = {
            key: STEP_RESULT_SKIPPED for key, _, _ in DEFAULT_STEP_CONFIG
        }
        task.has_meteor_today = False
        task.bless_sparkle_full = False
        task.pre_custom_step_results = []
        task.post_custom_step_results = []
        task.change_account_enabled = False
        task.update_task_result = Mock()
        return task

    @patch("whimbox.task.daily_task.all_in_one_task.daily_task.ZhaoxiTask")
    def test_zhaoxi_full_state_is_recorded(self, zhaoxi_task):
        zhaoxi_task.return_value.task_run.return_value = SimpleNamespace(
            status=STATE_TYPE_FAILED,
            data={"bless_sparkle_full": True},
        )
        task = self._make_task()

        task.step3()

        self.assertTrue(task.bless_sparkle_full)

    def test_single_account_summary_contains_full_warning(self):
        task = self._make_task()
        task.bless_sparkle_full = True

        task.step8()

        call = task.update_task_result.call_args
        self.assertIn(
            "❗祝福闪光已满，请及时使用，避免无法继续获取❗",
            call.kwargs["message"],
        )
        self.assertTrue(call.kwargs["data"]["bless_sparkle_full"])

    def test_multi_account_summary_contains_full_warning(self):
        task = self._make_task()

        lines = task._format_account_summary_lines(
            {
                "account_name": "测试账号",
                "default_steps": {},
                "bless_sparkle_full": True,
            }
        )

        self.assertIn(
            "❗祝福闪光已满，请及时使用，避免无法继续获取❗",
            lines,
        )

    def test_account_snapshot_retains_and_resets_full_state(self):
        task = self._make_task()
        task.current_account = "测试账号"
        task.account_results = []
        task.bless_sparkle_full = True

        task._snapshot_current_account_result()

        self.assertTrue(task.account_results[0]["bless_sparkle_full"])
        self.assertFalse(task.bless_sparkle_full)


if __name__ == "__main__":
    unittest.main()
