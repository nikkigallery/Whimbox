import unittest

from pydantic import ValidationError

from types import SimpleNamespace

from whimbox.common.scripts_manager import MacroRecord, PathRecord, analyze_macro_steps
from whimbox.task.navigation_task.common import resolve_loop_return_mode


class MacroLoopTests(unittest.TestCase):
    def test_nested_loop_expansion(self):
        record = MacroRecord.model_validate({
            "info": {"name": "nested", "type": "宏", "version": "3.1"},
            "steps": [
                {"type": "loop", "loop_count": 2, "loop_steps": 2},
                {"type": "loop", "loop_count": 3, "loop_steps": 1},
                {"type": "gap", "duration": 0.1},
            ],
        })
        self.assertEqual((2, 6), analyze_macro_steps(record.steps))

    def test_nested_loop_requires_31(self):
        with self.assertRaises(ValidationError):
            MacroRecord.model_validate({
                "info": {"name": "nested", "type": "宏", "version": "3.0"},
                "steps": [
                    {"type": "loop", "loop_count": 2, "loop_steps": 2},
                    {"type": "loop", "loop_count": 3, "loop_steps": 1},
                    {"type": "gap", "duration": 0.1},
                ],
            })


class PathLoopTests(unittest.TestCase):
    def _payload(self):
        return {
            "info": {"name": "route", "version": "2.1", "map": "miraland"},
            "points": [
                {
                    "id": 10, "move_mode": "WALK", "point_type": "TARGET",
                    "action": "TELEPORT", "position": [0, 0],
                },
                {
                    "id": 20, "move_mode": "WALK", "point_type": "TARGET",
                    "position": [100, 100],
                },
            ],
            "loops": [{
                "id": "segment-1", "start_point_id": 10, "end_point_id": 20,
                "loop_count": 3,
            }],
        }

    def test_route_loop_schema(self):
        record = PathRecord.model_validate(self._payload())
        self.assertEqual(3, record.loops[0].loop_count)

    def test_return_mode_prefers_teleport_start(self):
        start = SimpleNamespace(action="TELEPORT", position=[0, 0])
        end = SimpleNamespace(action=None, position=[100, 100])
        self.assertEqual("teleport", resolve_loop_return_mode(start, end))

    def test_return_mode_accepts_nearby_end(self):
        start = SimpleNamespace(action=None, position=[0, 0])
        end = SimpleNamespace(action=None, position=[3, 4])
        self.assertEqual("nearby", resolve_loop_return_mode(start, end))

    def test_return_mode_rejects_distant_end(self):
        start = SimpleNamespace(action=None, position=[0, 0])
        end = SimpleNamespace(action=None, position=[100, 100])
        with self.assertRaises(ValueError):
            resolve_loop_return_mode(start, end)


if __name__ == "__main__":
    unittest.main()
