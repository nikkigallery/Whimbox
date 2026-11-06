import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.common.cvars import (
    current_stop_flag,
    reset_task_pause,
    task_resume_generation,
    toggle_task_pause,
    wait_for_task_resume,
)
from whimbox.interaction.interaction_core import InteractionBGD
from whimbox.task.navigation_task.auto_path_task import AutoPathTask
from whimbox.task_manager import TaskManager


class TaskPauseTests(unittest.TestCase):
    def tearDown(self):
        reset_task_pause()

    def test_pause_waits_until_resumed_and_advances_generation(self):
        stop_flag = threading.Event()
        token = current_stop_flag.set(stop_flag)
        try:
            before = task_resume_generation()
            self.assertTrue(toggle_task_pause())
            done = threading.Event()
            worker = threading.Thread(target=lambda: (wait_for_task_resume(), done.set()))
            worker.start()
            self.assertFalse(done.wait(0.15))
            self.assertFalse(toggle_task_pause())
            self.assertTrue(done.wait(1))
            worker.join(1)
            self.assertEqual(task_resume_generation(), before + 1)
        finally:
            current_stop_flag.reset(token)

    def test_stopping_a_paused_task_unblocks_the_waiter(self):
        manager = TaskManager()
        info = manager.create("test-session", "test-tool")
        manager.set_state(info.task_id, "RUNNING")
        self.assertTrue(toggle_task_pause())
        finished = threading.Event()
        result = []

        def wait_as_task():
            token = current_stop_flag.set(info.stop_event)
            try:
                result.append(wait_for_task_resume())
            finally:
                current_stop_flag.reset(token)
                finished.set()

        worker = threading.Thread(target=wait_as_task)
        worker.start()
        self.assertFalse(finished.wait(0.15))
        self.assertTrue(manager.stop(info.task_id))
        self.assertTrue(finished.wait(1))
        worker.join(1)
        self.assertEqual(result, [False])

    def test_pause_releases_automation_held_input(self):
        interaction = object.__new__(InteractionBGD)
        interaction._held_input_lock = threading.Lock()
        interaction._held_keys = {"w"}
        interaction._held_mouse_buttons = {"left"}
        interaction.itt_exec = Mock()

        interaction.release_held_inputs()

        interaction.itt_exec.key_up.assert_called_once_with("w")
        interaction.itt_exec.left_up.assert_called_once_with()
        self.assertFalse(interaction._held_keys)
        self.assertFalse(interaction._held_mouse_buttons)

    def test_path_resume_uses_last_passed_teleporter_when_far(self):
        task = object.__new__(AutoPathTask)
        task.path_points = [
            SimpleNamespace(position=(0, 0)),
            SimpleNamespace(position=(100, 100)),
            SimpleNamespace(position=(200, 200)),
        ]
        task.path_info = SimpleNamespace(map="miraland")
        task.curr_target_point_id = 2
        task.last_teleport_point_id = 1
        task.move_controller = None
        task.jump_controller = None
        task.log_to_gui = Mock()
        task.clear_stuck = Mock()
        task.once_loop_time = 1

        with (
            patch("whimbox.task.navigation_task.auto_path_task.nikki_map") as game_map,
            patch("whimbox.task.navigation_task.auto_path_task.back_to_page_main"),
        ):
            game_map.map_name = "miraland"
            game_map.get_position.return_value = (0, 0)
            task._resume_after_pause()

        self.assertEqual(task.curr_target_point_id, 1)
        self.assertIsNone(task.last_position)
        self.assertEqual(task.once_loop_time, 0)

    def test_path_resume_keeps_current_target_when_near(self):
        task = object.__new__(AutoPathTask)
        task.path_points = [
            SimpleNamespace(position=(0, 0)),
            SimpleNamespace(position=(100, 100)),
        ]
        task.path_info = SimpleNamespace(map="miraland")
        task.curr_target_point_id = 1
        task.last_teleport_point_id = 0
        task.move_controller = None
        task.jump_controller = None
        task.log_to_gui = Mock()
        task.clear_stuck = Mock()

        with (
            patch("whimbox.task.navigation_task.auto_path_task.nikki_map") as game_map,
            patch("whimbox.task.navigation_task.auto_path_task.back_to_page_main"),
        ):
            game_map.map_name = "miraland"
            game_map.get_position.return_value = (99, 99)
            task._resume_after_pause()

        self.assertEqual(task.curr_target_point_id, 1)


if __name__ == "__main__":
    unittest.main()
