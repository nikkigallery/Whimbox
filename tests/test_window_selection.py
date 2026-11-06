import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from whimbox.common.handle_lib import ProcessHandler
from whimbox.interaction.capture import PrintWindowCapture
from whimbox.platform.windows.window import WindowsWindowManager


class WindowsWindowSelectionTests(unittest.TestCase):
    def setUp(self):
        self.manager = WindowsWindowManager()

    def find_with_windows(self, windows, *, previous_pid=None, foreground_pid=None):
        processes = [
            SimpleNamespace(info={"pid": pid, "name": "Game.exe"})
            for pid in windows
        ]
        with (
            patch("whimbox.platform.windows.window.psutil.process_iter", return_value=processes),
            patch.object(self.manager, "_get_hwnd_for_pid", side_effect=windows.get),
            patch.object(self.manager, "_log_window_selection"),
            patch("whimbox.platform.windows.window.win32gui.GetForegroundWindow", return_value=999 if foreground_pid else 0),
            patch("whimbox.platform.windows.window.win32process.GetWindowThreadProcessId", return_value=(1, foreground_pid)),
        ):
            return self.manager.find_process("Game.exe", previous_pid)

    def test_skips_windowless_leftover_process(self):
        self.assertEqual(self.find_with_windows({10: None, 20: 200}), 200)

    def test_prefers_foreground_game_over_previous_pid(self):
        self.assertEqual(
            self.find_with_windows({10: 100, 20: 200}, previous_pid=10, foreground_pid=20),
            200,
        )

    def test_keeps_previous_game_when_another_app_is_foreground(self):
        self.assertEqual(
            self.find_with_windows({10: 100, 20: 200}, previous_pid=10, foreground_pid=99),
            100,
        )

    def test_does_not_guess_between_two_background_game_windows(self):
        self.assertIsNone(self.find_with_windows({10: 100, 20: 200}))

    def test_returns_none_when_no_game_has_a_window(self):
        self.assertIsNone(self.find_with_windows({10: None, 20: None}))

    def test_picks_largest_nonempty_window_for_one_pid(self):
        def enumerate_windows(callback, arg):
            for hwnd in (100, 200, 300):
                callback(hwnd, arg)

        with (
            patch("whimbox.platform.windows.window.win32gui.EnumWindows", side_effect=enumerate_windows),
            patch("whimbox.platform.windows.window.win32process.GetWindowThreadProcessId", return_value=(1, 10)),
            patch("whimbox.platform.windows.window.win32gui.IsWindowVisible", return_value=True),
            patch("whimbox.platform.windows.window.win32gui.GetParent", return_value=0),
            patch("whimbox.platform.windows.window.win32gui.GetClientRect", side_effect=lambda hwnd: {
                100: (0, 0, 0, 0),
                200: (0, 0, 300, 200),
                300: (0, 0, 800, 600),
            }[hwnd]),
        ):
            self.assertEqual(self.manager._get_hwnd_for_pid(10), 300)


class ProcessHandlerSelectionTests(unittest.TestCase):
    def test_no_window_clears_stale_pid_and_cannot_close_by_name(self):
        manager = Mock()
        manager.find_process.return_value = None
        manager.is_alive.return_value = False
        with patch("whimbox.common.handle_lib.get_window_manager", return_value=manager):
            handler = ProcessHandler(process_name="Game.exe")
        handler.pid = 10

        handler.refresh_handle()

        self.assertIsNone(handler.pid)
        self.assertIsNone(handler.get_handle())
        self.assertIsNone(handler._get_process_pid())
        manager.get_pid.assert_not_called()

    def test_valid_window_pid_comes_from_selected_handle(self):
        manager = Mock()
        manager.find_process.return_value = 200
        manager.is_alive.return_value = True
        manager.get_pid.return_value = 20
        with patch("whimbox.common.handle_lib.get_window_manager", return_value=manager):
            handler = ProcessHandler(process_name="Game.exe")

        self.assertEqual(handler.get_handle(), 200)
        self.assertEqual(handler.pid, 20)
        manager.get_pid.assert_called_with(200, None)

    def test_foreground_change_rebinds_to_other_game_instance(self):
        manager = Mock()
        manager.find_process.side_effect = [100, 200]
        manager.is_alive.return_value = True
        manager.get_pid.side_effect = [10, 20]
        manager.is_foreground.return_value = False
        manager.has_foreground_process.return_value = True
        with patch("whimbox.common.handle_lib.get_window_manager", return_value=manager):
            handler = ProcessHandler(process_name="Game.exe")

        with patch("whimbox.common.handle_lib.time.monotonic", return_value=100):
            handler.refresh_if_foreground_changed()

        self.assertEqual(handler.get_handle(), 200)
        self.assertEqual(handler.pid, 20)
        manager.find_process.assert_called_with("Game.exe", 10)

    def test_other_foreground_app_does_not_rebind(self):
        manager = Mock()
        manager.find_process.return_value = 100
        manager.is_alive.return_value = True
        manager.get_pid.return_value = 10
        manager.is_foreground.return_value = False
        manager.has_foreground_process.return_value = False
        with patch("whimbox.common.handle_lib.get_window_manager", return_value=manager):
            handler = ProcessHandler(process_name="Game.exe")

        with patch("whimbox.common.handle_lib.time.monotonic", return_value=100):
            handler.refresh_if_foreground_changed()

        manager.find_process.assert_called_once()


class CaptureDiagnosticsTests(unittest.TestCase):
    def test_persistent_empty_capture_warning_is_rate_limited(self):
        handler = Mock()
        handler.get_handle.return_value = 200
        handler.pid = 20
        capture = PrintWindowCapture(handler)
        capture._cap_mgr = Mock()
        capture._cap_mgr.capture_window.return_value = np.zeros((4, 4, 4), dtype=np.uint8)

        with (
            patch("whimbox.interaction.capture.time.monotonic", side_effect=(1, 7, 8, 68)),
            patch("whimbox.interaction.capture.logger.warning") as warning,
        ):
            for _ in range(4):
                capture._get_capture()

        self.assertEqual(warning.call_count, 2)
        self.assertEqual(handler.refresh_if_foreground_changed.call_count, 4)


if __name__ == "__main__":
    unittest.main()
