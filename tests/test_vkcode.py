import unittest

from whimbox.interaction.vkcode import VK_CODE


class VirtualKeyCodeTests(unittest.TestCase):
    def test_recorded_key_names_match_windows_aliases(self) -> None:
        aliases = {
            "left": "left_arrow",
            "up": "up_arrow",
            "right": "right_arrow",
            "down": "down_arrow",
            "control": "ctrl",
            "insert": "ins",
            "delete": "del",
        }

        for recorded_name, canonical_name in aliases.items():
            with self.subTest(recorded_name=recorded_name):
                self.assertEqual(
                    VK_CODE[recorded_name],
                    VK_CODE[canonical_name],
                )


if __name__ == "__main__":
    unittest.main()
