import unittest
from unittest.mock import patch

from pydantic import ValidationError

from whimbox.common.keybind import keybind
from whimbox.common.scripts_manager import MacroRecord, MacroStep, PathRecord
from whimbox.task.macro_task.run_macro_task import RunMacroTask


class GameKeyScriptTests(unittest.TestCase):
    def test_route_game_key_requires_version_22(self):
        with self.assertRaises(ValidationError):
            PathRecord.model_validate(
                {
                    "info": {"name": "route", "version": "2.1"},
                    "points": [
                        {
                            "id": 1,
                            "move_mode": "WALK",
                            "point_type": "TARGET",
                            "action": "GAME_KEY_CLICK",
                            "action_params": "interaction",
                            "position": [0, 0],
                        }
                    ],
                }
            )

    def test_route_game_key_accepts_supported_binding(self):
        record = PathRecord.model_validate(
            {
                "info": {"name": "route", "version": "2.2"},
                "points": [
                    {
                        "id": 1,
                        "move_mode": "WALK",
                        "point_type": "TARGET",
                        "action": "GAME_KEY_CLICK",
                        "action_params": "interaction",
                        "position": [0, 0],
                    }
                ],
            }
        )

        self.assertEqual("interaction", record.points[0].action_params)

    def test_macro_game_key_requires_version_32(self):
        with self.assertRaises(ValidationError):
            MacroRecord.model_validate(
                {
                    "info": {"name": "macro", "type": "宏", "version": "3.1"},
                    "steps": [
                        {
                            "type": "game_key",
                            "key": "interaction",
                            "action": "press",
                        }
                    ],
                }
            )

    @patch("whimbox.task.macro_task.run_macro_task.itt")
    def test_macro_game_key_uses_current_user_binding(self, itt):
        task = object.__new__(RunMacroTask)
        task.pressing_keys = set()
        step = MacroStep(
            type="game_key",
            key="interaction",
            action="press",
        )

        with patch.object(keybind, "KEYBIND_INTERACTION", "mouse_x1"):
            task._execute_step(step)

        itt.key_down.assert_called_once_with("mouse_x1")
        self.assertEqual({"mouse_x1"}, task.pressing_keys)


if __name__ == "__main__":
    unittest.main()
