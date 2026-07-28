import unittest

from pydantic import ValidationError

from whimbox.common.scripts_manager import MacroRecord, PathRecord, analyze_macro_steps


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
    def _payload(self, end_position=(100, 100), return_mode="teleport"):
        return {
            "info": {"name": "route", "version": "2.1", "map": "miraland"},
            "points": [
                {
                    "id": 10, "move_mode": "WALK", "point_type": "TARGET",
                    "action": "TELEPORT", "position": [0, 0],
                },
                {
                    "id": 20, "move_mode": "WALK", "point_type": "TARGET",
                    "position": list(end_position),
                },
            ],
            "loops": [{
                "id": "segment-1", "start_point_id": 10, "end_point_id": 20,
                "loop_count": 3, "return_mode": return_mode, "nearby_distance": 10,
            }],
        }

    def test_teleport_loop(self):
        record = PathRecord.model_validate(self._payload())
        self.assertEqual(3, record.loops[0].loop_count)

    def test_nearby_loop_rejects_distant_end(self):
        with self.assertRaises(ValidationError):
            PathRecord.model_validate(self._payload(return_mode="nearby"))

    def test_nearby_loop_accepts_close_end(self):
        PathRecord.model_validate(
            self._payload(end_position=(3, 4), return_mode="nearby")
        )


if __name__ == "__main__":
    unittest.main()
