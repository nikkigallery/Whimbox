import unittest
from unittest.mock import Mock

from whimbox.task.daily_task.weekly_realm_task import WeeklyRealmTask
from whimbox.task.task_template import STATE_TYPE_FAILED, STEP_NAME_FINISH


class WeeklyRealmOverflowTests(unittest.TestCase):
    def test_full_warning_stops_remaining_challenges_and_preserves_result(self):
        task = object.__new__(WeeklyRealmTask)
        task.realm_target = ["第一关", "第二关"]
        task.bless_sparkle_full = False
        task.need_stop = Mock(return_value=False)
        task.quick_challenge = Mock(return_value=False)
        task.update_task_result = Mock()

        def mark_full(_realm_name):
            task.bless_sparkle_full = True
            return False

        task.quick_challenge.side_effect = mark_full

        self.assertEqual(task.step3(), STEP_NAME_FINISH)
        task.quick_challenge.assert_called_once_with("第一关")
        task.update_task_result.assert_not_called()

    def test_other_challenge_failure_does_not_report_completion(self):
        task = object.__new__(WeeklyRealmTask)
        task.realm_target = ["第一关", "第二关"]
        task.bless_sparkle_full = False
        task.need_stop = Mock(return_value=False)
        task.quick_challenge = Mock(return_value=False)
        task.update_task_result = Mock()

        self.assertEqual(task.step3(), STEP_NAME_FINISH)
        task.quick_challenge.assert_called_once_with("第一关")
        task.update_task_result.assert_called_once_with(
            status=STATE_TYPE_FAILED,
            message="第一关快速挑战失败",
        )


if __name__ == "__main__":
    unittest.main()
