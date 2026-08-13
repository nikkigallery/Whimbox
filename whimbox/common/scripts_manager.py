from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal
import os
import json
import threading

from whimbox.common.path_lib import SCRIPT_PATH
from whimbox.common.logger import logger

# 基础脚本信息
class ScriptInfo(BaseModel):
    name: str
    type: Optional[str] = None
    update_time: Optional[str] = None
    version: Optional[str] = None

# 跑图脚本信息
class PathInfo(ScriptInfo):
    target: Optional[str] = None # 目标：素材名
    count: Optional[int] = None # 目标数量
    region: Optional[str] = None
    map: Optional[str] = None
    test_mode: Optional[bool] = False

# 跑图脚本点位
class PathPoint(BaseModel):
    id: int
    move_mode: str          # 移动模式：行走、跳跃、飞行
    point_type: str      # 点位类型：途径点、必经点
    action: Optional[str] = None
    action_params: Optional[str] = None
    position: list[float]

class PathLoopSegment(BaseModel):
    """一段可重复执行的路线。loop_count 表示总执行轮数，0 表示无限循环。"""

    id: str
    name: Optional[str] = None
    start_point_id: int
    end_point_id: int
    loop_count: int = Field(default=1, ge=0)


# 跑图脚本
class PathRecord(BaseModel):
    info: PathInfo
    points: list[PathPoint]
    loops: list[PathLoopSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_loop_segments(self):
        if not self.loops:
            return self
        if self.info.version != "2.1":
            raise ValueError("包含循环分段的路线版本必须为2.1")

        point_id_to_index = {point.id: index for index, point in enumerate(self.points)}
        if len(point_id_to_index) != len(self.points):
            raise ValueError("路线点位id不能重复")

        loop_ids: set[str] = set()
        ranges: list[tuple[int, int, str]] = []
        for segment in self.loops:
            if not segment.id.strip():
                raise ValueError("循环分段id不能为空")
            if segment.id in loop_ids:
                raise ValueError(f"循环分段id重复: {segment.id}")
            loop_ids.add(segment.id)
            if segment.start_point_id not in point_id_to_index:
                raise ValueError(f"循环起点不存在: {segment.start_point_id}")
            if segment.end_point_id not in point_id_to_index:
                raise ValueError(f"循环终点不存在: {segment.end_point_id}")

            start_index = point_id_to_index[segment.start_point_id]
            end_index = point_id_to_index[segment.end_point_id]
            if start_index >= end_index:
                raise ValueError(f"循环分段{segment.id}的起点必须位于终点之前")
            start_point = self.points[start_index]
            end_point = self.points[end_index]
            if start_point.point_type != "TARGET" or end_point.point_type != "TARGET":
                raise ValueError(f"循环分段{segment.id}的起点和终点必须是必经点")
            if segment.loop_count == 0 and end_index != len(self.points) - 1:
                raise ValueError(f"无限循环分段{segment.id}必须以路线最后一个点为终点")
            ranges.append((start_index, end_index, segment.id))

        ranges.sort(key=lambda item: item[0])
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] <= previous[1]:
                raise ValueError(
                    f"路线循环分段不能重叠: {previous[2]} 与 {current[2]}"
                )
        return self


# 宏脚本信息
class MacroInfo(ScriptInfo):
    aspect_ratio: Optional[Literal["16:9", "16:10"]] = None  # 分辨率比例

# 宏脚本步骤
class MacroStep(BaseModel):
    type: Literal["gap", "keyboard", "mouse", "loop", "wait_game_page", "wait_not_game_page", "goto_game_page"]  # 操作类型
    key: Optional[str] = None  # 键盘按键名称或鼠标按键名称
    action: Optional[Literal["press", "release"]] = None  # 按键动作：按下/松开
    position: Optional[tuple[int, int]] = None  # 鼠标位置（窗口内坐标，归一化到 width=1920）
    duration: Optional[float] = None  # 间隔时间（秒），仅当 type="gap" 时有效
    loop_count: Optional[int] = None  # 循环次数（仅当 type="loop" 时有效）
    loop_steps: Optional[int] = None  # 循环的步骤数量（仅当 type="loop" 时有效，表示接下来几个步骤需要循环）
    target_game_page: Optional[str] = None  # 等待某个特定游戏页面（仅当 type="wait_game" 时有效）

# 宏脚本
class MacroRecord(BaseModel):
    info: MacroInfo
    steps: list[MacroStep] = Field(default_factory=list)  # 操作步骤列表

    @model_validator(mode="after")
    def validate_loop_structure(self):
        max_depth, _ = analyze_macro_steps(self.steps)
        if max_depth > 1 and self.info.version != "3.1":
            raise ValueError("包含嵌套循环的宏版本必须为3.1")
        return self


MAX_MACRO_LOOP_DEPTH = 8
MAX_MACRO_EXPANDED_STEPS = 1_000_000


def analyze_macro_steps(steps: list[MacroStep]) -> tuple[int, int]:
    """校验扁平宏循环范围，并返回最大嵌套深度和理论展开步骤数。"""

    def walk(start: int, end: int, depth: int) -> tuple[int, int]:
        if depth > MAX_MACRO_LOOP_DEPTH:
            raise ValueError(f"宏循环嵌套不能超过{MAX_MACRO_LOOP_DEPTH}层")
        max_depth = depth
        expanded_steps = 0
        index = start
        while index < end:
            step = steps[index]
            if step.type != "loop":
                expanded_steps += 1
                index += 1
                continue

            if not step.loop_count or step.loop_count < 1:
                raise ValueError(f"第{index + 1}步循环次数必须大于0")
            if not step.loop_steps or step.loop_steps < 1:
                raise ValueError(f"第{index + 1}步循环范围必须至少包含1个步骤")
            body_end = index + 1 + step.loop_steps
            if body_end > end:
                raise ValueError(f"第{index + 1}步循环范围超出当前父循环")

            child_depth, child_expanded = walk(index + 1, body_end, depth + 1)
            max_depth = max(max_depth, child_depth)
            expanded_steps += child_expanded * step.loop_count
            if expanded_steps > MAX_MACRO_EXPANDED_STEPS:
                raise ValueError(
                    f"宏理论执行步骤不能超过{MAX_MACRO_EXPANDED_STEPS}"
                )
            index = body_end
        return max_depth, expanded_steps

    return walk(0, len(steps), 0)


class ScriptsManager:

    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(ScriptsManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._scripts_lock = threading.RLock()
        self._scripts_version = 0
        self.path_dict = {}
        self.macro_dict = {}
        self.init_scripts_dict()

        self._initialized = True

    def init_scripts_dict(self) -> dict:
        path_dict: dict[str, PathRecord] = {}
        macro_dict: dict[str, MacroRecord] = {}
        # 使用 os.walk 递归遍历所有子文件夹
        for root, _, files in os.walk(SCRIPT_PATH):
            for file in files:
                if file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        try:
                            json_text = f.read()
                            json_dict = json.loads(json_text)
                            if json_dict['info']['type'] == '宏' or json_dict['info']['type'] == '乐谱':
                                macro_record = MacroRecord.model_validate_json(json_text)
                                macro_name = macro_record.info.name
                                if macro_name in macro_dict:
                                    if macro_dict[macro_name].info.update_time < macro_record.info.update_time:
                                        macro_dict[macro_name] = macro_record
                                    else:
                                        continue
                                else:
                                    macro_dict[macro_name] = macro_record
                            else:
                                path_record = PathRecord.model_validate_json(json_text)
                                path_name = path_record.info.name
                                if path_name in path_dict:
                                    if path_dict[path_name].info.update_time < path_record.info.update_time:
                                        path_dict[path_name] = path_record
                                    else:
                                        continue
                                else:
                                    path_dict[path_name] = path_record
                        except Exception as e:
                            logger.error(f"读取脚本文件{file_path}失败: {e}")
                            continue

        with self._scripts_lock:
            self.path_dict = path_dict
            self.macro_dict = macro_dict
            self._scripts_version += 1
            version = self._scripts_version

        return {
            "version": version,
            "path_count": len(path_dict),
            "macro_count": sum(record.info.type != "乐谱" for record in macro_dict.values()),
            "music_count": sum(record.info.type == "乐谱" for record in macro_dict.values()),
        }

    def query_path(self, path_name=None, name=None, target=None, type=None, count=None, return_one=False, show_default=False) -> list[PathRecord] | PathRecord | None:
        with self._scripts_lock:
            path_dict = self.path_dict
        # 指定名字就直接返回单文件（用于内部固定路线的任务使用，比如每日任务）
        if path_name:
            return path_dict.get(path_name, None)
        
        # 根据要求进行筛选
        res = []
        for _, path_record in path_dict.items():
            match = True
            
            if (not show_default) and (
                path_record.info.name.startswith("朝夕心愿_") 
                or path_record.info.name.startswith("星海拾光_")
                or path_record.info.name.startswith("家园日常")):
                match = False

            if name is not None:
                if name.lower() not in path_record.info.name.lower():
                    match = False

            # Filter by target (fuzzy match)
            if target is not None:
                if path_record.info.target is None or target.lower() not in path_record.info.target.lower():
                    match = False
            
            # Filter by type (exact match)
            if type is not None:
                if path_record.info.type != type:
                    match = False
            
            # Filter by count (greater than or equal)
            if count is not None:
                if path_record.info.count is None or path_record.info.count < count:
                    match = False
            
            if match:
                res.append(path_record)
        
        if return_one:
            return res[0] if res else None
        else:
            return res

    def search_path_items(
        self,
        name=None,
        target=None,
        type=None,
        count=None,
        limit=5,
        show_default=False,
    ) -> list[dict]:
        path_records = self.query_path(
            name=name,
            target=target,
            type=type,
            count=count,
            show_default=show_default,
        )
        if not path_records:
            return []

        sorted_records = sorted(path_records, key=lambda record: record.info.name)
        if limit is not None and limit > 0:
            sorted_records = sorted_records[:limit]

        return [
            {
                "path_name": path_record.info.name,
                # "target": path_record.info.target,
                # "type": path_record.info.type,
                # "count": path_record.info.count,
                # "region": path_record.info.region,
                # "map": path_record.info.map,
            }
            for path_record in sorted_records
        ]

    def search_macro_items(
        self,
        name=None,
        *,
        is_play_music=False,
        limit=5,
        show_default=False,
    ) -> list[dict]:
        macro_records = self.query_macro(
            name=name,
            is_play_music=is_play_music,
            show_default=show_default,
        )
        if not macro_records:
            return []

        sorted_records = sorted(macro_records, key=lambda record: record.info.name)
        if limit is not None and limit > 0:
            sorted_records = sorted_records[:limit]

        return [
            {
                "macro_name": macro_record.info.name,
                "type": macro_record.info.type,
            }
            for macro_record in sorted_records
        ]

    def _is_macro_type(self, script_type: Optional[str]) -> bool:
        return script_type in ("宏", "乐谱")

    def _find_script_files_by_name(self, script_name: str, is_macro: bool) -> list[str]:
        """
        递归查找指定名称的脚本文件。

        Args:
            script_name: 脚本名称
            is_macro: True 查找宏/乐谱，False 查找跑图路线
        """
        target_filepaths: list[str] = []
        for root, _, files in os.walk(SCRIPT_PATH):
            for file in files:
                if not file.endswith(".json"):
                    continue

                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                except (json.JSONDecodeError, KeyError, TypeError):
                    # 跳过格式错误的文件
                    continue
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

                info = script_data.get("info", {})
                if info.get("name") != script_name:
                    continue

                script_type = info.get("type")
                if is_macro and not self._is_macro_type(script_type):
                    continue
                if not is_macro and self._is_macro_type(script_type):
                    continue
                target_filepaths.append(file_path)

        return target_filepaths
    
    def delete_path(self, path_name: str) -> int:
        """
        删除指定名称的路线
        
        Args:
            path_name: 路线名称
            
        Returns:
            删除的文件数量，如果出错返回 0
        """
        if not path_name:
            logger.warning("Path name is empty, cannot delete")
            return 0
        
        if not os.path.exists(SCRIPT_PATH):
            logger.warning(f"Script path does not exist: {SCRIPT_PATH}")
            return 0
        
        try:
            target_filepath = self._find_script_files_by_name(path_name, is_macro=False)

            # 删除成功后，重新初始化路径字典
            deleted_count = 0
            for file_path in target_filepath:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete file {file_path}: {e}")
                    continue
            if deleted_count > 0:
                self.init_scripts_dict()
                logger.info(f"Deleted {deleted_count} file(s) for path '{path_name}'")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to delete path '{path_name}': {e}")
            return 0

    def open_path_folder(self):
        """打开路线文件夹"""
        try:
            if os.path.exists(SCRIPT_PATH):
                os.startfile(SCRIPT_PATH)
                logger.info(f"Opened path folder: {SCRIPT_PATH}")
            else:
                return False, f"路线文件夹不存在:{SCRIPT_PATH}"
        except Exception as e:
            logger.error(f"Failed to open path folder: {e}")
            return False, f"无法打开路线文件夹:{str(e)}"
        return True, f"已打开路线文件夹:{SCRIPT_PATH}"

    def query_macro(self, name=None, is_play_music=False, return_one=False, show_default=False) -> list[MacroRecord] | MacroRecord | None:
        """
        查询宏
        
        Args:
            name: 宏名称，如果提供则返回单个宏，否则返回所有宏的列表（支持模糊匹配）
            
        Returns:
            如果指定name且找到，返回单个MacroRecord；如果name为None，返回匹配的列表
        """
        with self._scripts_lock:
            macro_dict = self.macro_dict

        # 指定名字就直接返回单文件
        if name:
            # 尝试精确匹配
            if name in macro_dict:
                if return_one:
                    return macro_dict[name]
                else:
                    return [macro_dict[name]]
            
            # 模糊匹配
            res = []
            for macro_name, macro_record in macro_dict.items():
                if (not show_default) and (
                    macro_record.info.name.startswith("朝夕心愿_") 
                    or macro_record.info.name.startswith("星海拾光_")
                    or macro_record.info.name.startswith("家园日常")):
                    continue
                if name.lower() in macro_name.lower():
                    if macro_record.info.type == "乐谱" and is_play_music:
                        if return_one:
                            return macro_record
                        else:
                            res.append(macro_record)
                    elif macro_record.info.type != "乐谱" and not is_play_music:
                        if return_one:
                            return macro_record
                        else:
                            res.append(macro_record)
            if return_one:
                return res[0] if res else None
            else:
                return res
        
        # 返回所有宏
        res = []
        for _, macro_record in macro_dict.items():
            if (not show_default) and (
                macro_record.info.name.startswith("朝夕心愿_") 
                or macro_record.info.name.startswith("星海拾光_")
                or macro_record.info.name.startswith("家园日常")):
                continue
            if macro_record.info.type == "乐谱" and is_play_music:
                if return_one:
                    return macro_record
                else:
                    res.append(macro_record)
            elif macro_record.info.type != "乐谱" and not is_play_music:
                if return_one:
                    return macro_record
                else:
                    res.append(macro_record)
        if return_one:
            return res[0] if res else None
        else:
            return res
    
    def delete_macro(self, macro_name: str) -> int:
        """
        删除指定名称的宏
        
        Args:
            macro_name: 宏名称
            
        Returns:
            删除的文件数量，如果出错返回 0
        """
        if not macro_name:
            logger.warning("Macro name is empty, cannot delete")
            return 0
        
        if not os.path.exists(SCRIPT_PATH):
            logger.warning(f"Script path does not exist: {SCRIPT_PATH}")
            return 0
        
        try:
            target_filepath = self._find_script_files_by_name(macro_name, is_macro=True)

            # 删除成功后，重新初始化脚本字典
            deleted_count = 0
            for file_path in target_filepath:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete file {file_path}: {e}")
                    continue
            if deleted_count > 0:
                self.init_scripts_dict()
                logger.info(f"Deleted {deleted_count} file(s) for macro '{macro_name}'")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to delete macro '{macro_name}': {e}")
            return 0
    
    def open_macro_folder(self):
        """打开宏文件夹（实际上和路线文件夹是同一个）"""
        try:
            if os.path.exists(SCRIPT_PATH):
                os.startfile(SCRIPT_PATH)
                logger.info(f"Opened macro folder: {SCRIPT_PATH}")
            else:
                return False, f"宏文件夹不存在:{SCRIPT_PATH}"
        except Exception as e:
            logger.error(f"Failed to open macro folder: {e}")
            return False, f"无法打开宏文件夹:{str(e)}"
        return True, f"已打开宏文件夹:{SCRIPT_PATH}"

scripts_manager = ScriptsManager()
