import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whimbox.common.cvars import (
    TaskResumedDuringRestartableOperation,
    current_stop_flag,
    reset_task_pause,
    restart_operation_on_task_resume,
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

    def test_restartable_operation_interrupts_after_resume(self):
        with self.assertRaises(TaskResumedDuringRestartableOperation):
            with restart_operation_on_task_resume():
                self.assertTrue(toggle_task_pause())
                self.assertFalse(toggle_task_pause())

    def test_restartable_operation_preserves_stop_request(self):
        stop_flag = threading.Event()
        token = current_stop_flag.set(stop_flag)
        try:
            with restart_operation_on_task_resume():
                self.assertTrue(toggle_task_pause())
                stop_flag.set()
                self.assertFalse(wait_for_task_resume())
        finally:
            current_stop_flag.reset(token)

    def test_path_teleport_returns_to_main_and_retries_after_resume(self):
        task = object.__new__(AutoPathTask)
        task.stop_flag = threading.Event()
        task.path_info = SimpleNamespace(map="miraland")
        task.jump_controller = None
        task.last_position = (1, 2)
        task.once_loop_time = 1
        task._teleport_resume_handled_generation = None
        task.need_stop = Mock(return_value=False)
        task.stop_move = Mock()
        task.clear_stuck = Mock()
        task.log_to_gui = Mock()

        attempts = []

        def teleport(*args):
            attempts.append(args)
            if len(attempts) == 1:
                self.assertTrue(toggle_task_pause())
                self.assertFalse(toggle_task_pause())
                wait_for_task_resume()

        with (
            patch("whimbox.task.navigation_task.auto_path_task.nikki_map.bigmap_tp", side_effect=teleport),
            patch("whimbox.task.navigation_task.auto_path_task.back_to_page_main", return_value=True) as back,
        ):
            self.assertTrue(task._teleport_with_pause_recovery((10, 20)))

        self.assertEqual(attempts, [((10, 20), "miraland")] * 2)
        back.assert_called_once_with(timeout=30, max_esc=12)
        self.assertEqual(task._teleport_resume_handled_generation, task_resume_generation())
        self.assertIsNone(task.last_position)
        self.assertEqual(task.once_loop_time, 0)

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

    def test_path_stop_cleanup_skips_capture_and_releases_held_inputs(self):
        task = object.__new__(AutoPathTask)
        task.stop_flag = threading.Event()
        task.stop_flag.set()
        task.last_teleport_point_id = 0
        task.click_skip_monitor = None
        task.move_controller = Mock()
        task.jump_controller = Mock()
        task.stop_move = Mock()
        task.change_to_walk = Mock()

        with patch("whimbox.task.navigation_task.auto_path_task.itt") as interaction:
            task.clear_all()

        task.change_to_walk.assert_not_called()
        interaction.release_held_inputs.assert_called_once_with()
        self.assertIsNone(task.jump_controller)
        self.assertIsNone(task.move_controller)

    def test_path_stop_during_cleanup_capture_does_not_raise(self):
        task = object.__new__(AutoPathTask)
        task.stop_flag = threading.Event()
        task.last_teleport_point_id = 0
        task.click_skip_monitor = None
        task.move_controller = Mock()
        task.jump_controller = Mock()
        task.stop_move = Mock()

        def stop_during_capture():
            task.stop_flag.set()
            raise RuntimeError("capture aborted by stop")

        task.change_to_walk = Mock(side_effect=stop_during_capture)
        with patch("whimbox.task.navigation_task.auto_path_task.itt") as interaction:
            task.clear_all()

        interaction.release_held_inputs.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
