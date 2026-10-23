import unittest
from unittest.mock import patch

from whimbox.task.daily_task.zhaoxi_task import ZhaoxiTask
from whimbox.task.task_template import STATE_TYPE_FAILED, TaskResult, TaskTemplate


class ZhaoxiBlessSparkleTest(unittest.TestCase):
    def test_bless_full_state_is_preserved_in_final_result(self):
        task = object.__new__(ZhaoxiTask)
        task.bless_sparkle_full = False
        task.task_result = TaskResult(
            status=STATE_TYPE_FAILED,
            message="朝夕心愿未完成",
            data={"existing": True},
        )
        task._record_bless_result(
            TaskResult(data={"bless_sparkle_full": True})
        )

        with patch.object(TaskTemplate, "handle_finally"):
            task.handle_finally()

        self.assertTrue(task.bless_sparkle_full)
        self.assertEqual(
            task.task_result.data,
            {"existing": True, "bless_sparkle_full": True},
        )


if __name__ == "__main__":
    unittest.main()
