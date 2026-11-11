import unittest
from unittest.mock import Mock

from whimbox.action.fishing import FishingResult, FishingTask


class FishingStopTests(unittest.TestCase):
    def test_stop_while_waiting_for_fishing_does_not_capture_again(self):
        task = object.__new__(FishingTask)
        task.need_stop = Mock(return_value=True)
        task.get_current_state = Mock(side_effect=AssertionError("stopped task must not capture"))

        self.assertEqual(task.fishing_loop(), FishingResult.SUCCESS)
        task.get_current_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
