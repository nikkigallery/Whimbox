import string
from whimbox.interaction.vkcode import VK_CODE


class InteractionTemplate:
    """Base class / stub for interaction implementations.

    Concrete behaviour is provided by InteractionNormal (which delegates to
    the platform InputManager). This class exists so that call-sites can rely
    on the method signatures without caring about the platform.
    """

    def __init__(self):
        pass

    def left_click(self):
        pass

    def left_down(self):
        pass

    def left_up(self):
        pass

    def left_double_click(self, dt=0.05):
        pass

    def right_down(self):
        pass

    def right_up(self):
        pass

    def right_click(self):
        pass

    def middle_down(self):
        pass

    def middle_up(self):
        pass

    def middle_click(self):
        pass

    def key_down(self, key):
        pass

    def key_up(self, key):
        pass

    def key_press(self, key):
        pass

    def move_to(self, x: int, y: int, relative=False):
        pass

    def drag(self, origin_xy: list, target_xy: list):
        pass

    def get_virtual_keycode(self, key: str) -> int:
        """根据按键名获取虚拟按键码

        Concrete implementations override this via the platform InputManager.
        This fallback uses a simple VK_CODE table lookup.

        Args:
            key (str): 按键名

        Returns:
            int: 虚拟按键码
        """
        if len(key) == 1 and key in string.printable:
            # Printable single characters: defer to the platform manager
            # (Windows uses VkKeyScanA; macOS uses its own table).
            # Return 0 here; concrete subclasses must override.
            return 0
        else:
            return VK_CODE[key.lower()]