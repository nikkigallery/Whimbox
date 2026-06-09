import os
import configparser
import shutil
from typing import Any
import json
from whimbox.common.path_lib import CONFIG_PATH, ASSETS_PATH
from whimbox.config.default_config import DEFAULT_CONFIG, get_default_value


class GlobalConfig:
    """
    配置管理类
    支持INI格式配置文件的读写操作
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(GlobalConfig, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """
        初始化配置管理器
        """
        if self._initialized:
            return
        
        self.config_file = os.path.join(CONFIG_PATH, "config.json")
        self.config = {}
        self._update_user_config()
        self._load_config()
        self._initialized = True
    
    def _update_user_config(self):
        """确保配置目录存在，并检查新增的默认配置项"""
        if not os.path.exists(CONFIG_PATH):
            os.makedirs(CONFIG_PATH, exist_ok=True)

        # 如果配置不存在，就直接复制默认配置
        if not os.path.exists(self.config_file):
            shutil.copy2(os.path.join(ASSETS_PATH, "default_config.json"), self.config_file)
        else:
            # 如果配置存在，就检查新增的默认配置项
            with open(self.config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            
            # 旧按键名到新按键名的映射（兼容旧版本配置）
            key_name_mapping = {
                '鼠标左键': 'mouse_left',
                '鼠标右键': 'mouse_right',
                '鼠标中键': 'mouse_middle',
                '鼠标侧键1': 'mouse_x1',
                '鼠标侧键2': 'mouse_x2',
            }
            
            for section_name, section_data in DEFAULT_CONFIG.items():
                if section_name not in user_config:
                    user_config[section_name] = {}
                for key, config_item in section_data.items():
                    if key not in user_config[section_name]:
                        user_config[section_name][key] = config_item
                    else:
                        user_config[section_name][key]['description'] = config_item['description']
                        # 转换旧的按键名为新的按键名
                        if section_name == 'Keybinds' and 'value' in user_config[section_name][key]:
                            old_value = user_config[section_name][key]['value']
                            if old_value in key_name_mapping:
                                user_config[section_name][key]['value'] = key_name_mapping[old_value]
                        if section_name == 'OneDragon' and key == 'realm_target' and 'value' in user_config[section_name][key]:
                            old_value = user_config[section_name][key]['value']
                            if isinstance(old_value, str):
                                if old_value == '全部':
                                    user_config[section_name][key]['value'] = list(config_item.get('value', []))
                                elif old_value == '不做周本' or not old_value:
                                    user_config[section_name][key]['value'] = []
                                else:
                                    user_config[section_name][key]['value'] = [old_value]
            
            # 删除已经不存在的配置项
            sections_to_delete = [section_name for section_name in user_config 
                                 if section_name not in DEFAULT_CONFIG]
            for section_name in sections_to_delete:
                del user_config[section_name]
            for section_name in user_config:
                keys_to_delete = [key for key in user_config[section_name] 
                                if key not in DEFAULT_CONFIG[section_name]]
                for key in keys_to_delete:
                    del user_config[section_name][key]
            # 保存更新后的配置
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(user_config, f, ensure_ascii=False, indent=4)

    def _load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                print(f"警告: 加载配置文件失败: {e}")
                self.config = {}
        else:
            self.config = {}
    
    def get(self, section: str, key: str, default: Any = None) -> str:
        """
        获取配置项的字符串值
        
        Args:
            section: 配置节名
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        try:
            return self.config[section][key]['value']
        except KeyError:
            if default is not None:
                return str(default)
            # 尝试从默认配置获取
            return get_default_value(section, key, str)
    
    def get_int(self, section: str, key: str, default: int = None) -> int:
        """
        获取配置项的整数值
        
        Args:
            section: 配置节名
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        try:
            return int(self.config[section][key]['value'])
        except Exception as e:
            if default is not None:
                return default
            # 尝试从默认配置获取
            return get_default_value(section, key, int)
    
    def get_float(self, section: str, key: str, default: float = None) -> float:
        """
        获取配置项的浮点数值
        
        Args:
            section: 配置节名
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        try:
            return float(self.config[section][key]['value'])
        except Exception as e:
            if default is not None:
                return default
            # 尝试从默认配置获取
            return get_default_value(section, key, float)
    
    def get_bool(self, section: str, key: str, default: bool = None) -> bool:
        """
        获取配置项的布尔值
        
        Args:
            section: 配置节名
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        try:
            return self.config[section][key]['value'].lower() in ('true', '1', 'yes', 'on')
        except Exception as e:
            if default is not None:
                return default
            # 尝试从默认配置获取
            return get_default_value(section, key, bool)
    

    def set(self, section: str, key: str, value: Any) -> None:
        """设置配置项的值"""
        if section not in self.config:
            self.config[section] = {}
        if key not in self.config[section]:
            self.config[section][key] = {}
        
        # 保持描述信息
        description = self.config[section][key].get('description', '')
        if not description and section in DEFAULT_CONFIG and key in DEFAULT_CONFIG[section]:
            description = DEFAULT_CONFIG[section][key].get('description', '')
        
        self.config[section][key] = {
            'value': value,
            'description': description
        }
        # 如果更新了键位设置，就要update一下
        if section == "Keybinds":
            from whimbox.common.keybind import keybind
            keybind.update_keybind()

    def save(self) -> bool:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            return False

    def reload(self) -> None:
        """重新加载配置文件"""
        self._load_config()

# 创建全局配置实例
global_config = GlobalConfig()

if __name__ == "__main__":
    print(global_config.get("OneDragon", "energy_cost"))
