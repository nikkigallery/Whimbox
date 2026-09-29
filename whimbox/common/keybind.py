from whimbox.config.config import global_config
from whimbox.common.game_keybinds import GAME_KEYBIND_ATTRIBUTES

class KeybindRef:
    def __init__(self, keybind_obj, attr_name: str):
        self.keybind_obj = keybind_obj
        self.attr_name = attr_name

    def resolve(self):
        return getattr(self.keybind_obj, self.attr_name)

    def __str__(self):
        return self.resolve()

class Keybind:
    def __init__(self):
        self.KEYBIND_MAP = "m"
        self.KEYBIND_DAILY_TASK = "l"
        self.KEYBIND_DRESS = "c"
        self.KEYBIND_TAKE_PHOTO = "p"
        self.KEYBIND_MONTHLY_PASS = "j"
        self.KEYBIND_ITEM = "z"
        self.KEYBIND_EVENT = "k"
        self.KEYBIND_INTERACTION = "f"
        self.KEYBIND_BELL = "x"
        self.KEYBIND_ABILITY_DERIVATION_WORLD_1 = "g"
        self.KEYBIND_ABILITY_DERIVATION_1 = "r"
        self.KEYBIND_FORWARD = "w"
        self.KEYBIND_JUMP = "space"
        self.KEYBIND_FALLING = "q"
        self.KEYBIND_SPRINT = "shift"
        self.KEYBIND_TAB = "tab"
        self.KEYBIND_FISHING_REEL_IN = "mouse_right"
        self.KEYBIND_BACK = "backspace"
        self.KEYBIND_CHAT = "enter"
        self.KEYBIND_ABILITY_1 = "1"
        self.KEYBIND_ABILITY_2 = "2"
        self.KEYBIND_ABILITY_3 = "3"
        self.KEYBIND_ABILITY_4 = "4"
        self.KEYBIND_ABILITY_5 = "5"
        self.KEYBIND_ABILITY_6 = "6"
        self.KEYBIND_ABILITY_7 = "7"
        self.KEYBIND_ABILITY_8 = "8"
        self.update_keybind()

    def update_keybind(self):
        self.KEYBIND_MAP = global_config.get('Keybinds', 'map')
        self.KEYBIND_DAILY_TASK = global_config.get('Keybinds', 'daily_task')
        self.KEYBIND_DRESS = global_config.get('Keybinds', 'dress')
        self.KEYBIND_TAKE_PHOTO = global_config.get('Keybinds', 'take_photo')
        self.KEYBIND_MONTHLY_PASS = global_config.get('Keybinds', 'monthly_pass')
        self.KEYBIND_ITEM = global_config.get('Keybinds', 'item')
        self.KEYBIND_EVENT = global_config.get('Keybinds', 'event')
        self.KEYBIND_INTERACTION = global_config.get('Keybinds', 'interaction')
        self.KEYBIND_BELL = global_config.get('Keybinds', 'bell')
        self.KEYBIND_ABILITY_DERIVATION_WORLD_1 = global_config.get('Keybinds', 'ability_derivation_world_1')
        self.KEYBIND_ABILITY_DERIVATION_1 = global_config.get('Keybinds', 'ability_derivation_1')
        self.KEYBIND_FORWARD = global_config.get('Keybinds', 'forward')
        self.KEYBIND_JUMP = global_config.get('Keybinds', 'jump')
        self.KEYBIND_FALLING = global_config.get('Keybinds', 'falling')
        self.KEYBIND_SPRINT = global_config.get('Keybinds', 'sprint')
        self.KEYBIND_TAB = global_config.get('Keybinds', 'tab')
        self.KEYBIND_FISHING_REEL_IN = global_config.get('Keybinds', 'fishing_reel_in')
        self.KEYBIND_BACK = global_config.get('Keybinds', 'back')
        self.KEYBIND_CHAT = global_config.get('Keybinds', 'chat')
        self.KEYBIND_ABILITY_1 = global_config.get('Keybinds', 'ability_1')
        self.KEYBIND_ABILITY_2 = global_config.get('Keybinds', 'ability_2')
        self.KEYBIND_ABILITY_3 = global_config.get('Keybinds', 'ability_3')
        self.KEYBIND_ABILITY_4 = global_config.get('Keybinds', 'ability_4')
        self.KEYBIND_ABILITY_5 = global_config.get('Keybinds', 'ability_5')
        self.KEYBIND_ABILITY_6 = global_config.get('Keybinds', 'ability_6')
        self.KEYBIND_ABILITY_7 = global_config.get('Keybinds', 'ability_7')
        self.KEYBIND_ABILITY_8 = global_config.get('Keybinds', 'ability_8')

    def ref(self, attr_name: str):
        return KeybindRef(self, attr_name)

    def resolve_game_key(self, game_key: str) -> str:
        attr_name = GAME_KEYBIND_ATTRIBUTES.get(str(game_key or "").strip())
        if attr_name is None:
            raise ValueError(f"不支持的游戏按键: {game_key}")
        return getattr(self, attr_name)

keybind = Keybind()
