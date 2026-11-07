import unittest
from threading import Lock
from unittest.mock import Mock, patch

from whimbox.task.navigation_task import record_path_task
from whimbox.task.navigation_task.record_path_task import RecordPathTask
from whimbox.common.scripts_manager import PathPoint


class RecordPathSaveTests(unittest.TestCase):
    def test_save_after_stop_uses_cached_position_and_move_mode(self):
        task = object.__new__(RecordPathTask)
        task._lock = Lock()
        task.path_point_list = [
            PathPoint(
                id=0,
                move_mode=record_path_task.MOVE_MODE_JUMP,
                point_type=record_path_task.POINT_TYPE_TARGET,
                position=[10, 20],
            )
        ]
        task.log_to_gui = Mock()
        task.update_task_result = Mock()

        with (
            patch.object(record_path_task.nikki_map, "get_position", return_value=[12, 34]) as get_position,
            patch.object(record_path_task.nikki_map, "update_region_and_map_name", return_value=("test", "miraland")),
            patch.object(record_path_task, "get_move_mode_in_game", side_effect=AssertionError("must not capture after stop")),
            patch.object(record_path_task, "convert_PngMapPx_to_GameLoc", side_effect=lambda pos, *_args, **_kwargs: pos),
            patch.object(record_path_task, "optimize_path"),
            patch.object(record_path_task, "save_json") as save_json,
            patch.object(record_path_task.os.path, "exists", return_value=True),
        ):
            task.save_path()

        get_position.assert_called_once_with(use_cache=True)
        saved_points = save_json.call_args.args[0]["points"]
        self.assertEqual(saved_points[-1]["position"], [12.0, 34.0])
        self.assertEqual(saved_points[-1]["move_mode"], record_path_task.MOVE_MODE_JUMP)
        self.assertEqual(saved_points[-1]["point_type"], record_path_task.POINT_TYPE_TARGET)
        task.update_task_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
