from typing import Any, Dict
import time

from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.common.logger import logger
from whimbox.common.notification import send_notification
from whimbox.rpc_server import notify_event
from whimbox.common.scripts_manager import scripts_manager
from whimbox.task.common_task.start_game_task import StartGameTask
from whimbox.task.common_task.goto_ui_task import GotoUITask
from whimbox.task.daily_task import (
    JihuaTask,
    BlessTask,
    MonsterTask,
    DigTaskV2,
    ZhaoxiTask,
    AllInOneTask,
    MonthlyPassTask,
    WeeklyRealmTask,
    XinghaiTask,
)
from whimbox.task.daily_task.xinghai_run_task import XinghaiRunTask
from whimbox.task.macro_task.record_macro_task import RecordMacroTask
from whimbox.task.macro_task.run_macro_task import RunMacroTask
from whimbox.task.mira_crown_task.mira_crown_task import MiraCrownTask
from whimbox.task.navigation_task.auto_path_task import AutoPathTask
from whimbox.task.navigation_task.record_path_task import RecordPathTask
from whimbox.task.photo_task.daily_photo_task import DailyPhotoTask
from whimbox.task.task_template import STATE_TYPE_ERROR, STATE_TYPE_SUCCESS, TaskResult
from whimbox.task_adapter import TaskAdapter


def _error(message: str) -> Dict[str, Any]:
    return TaskResult(STATE_TYPE_ERROR, message).to_dict()


def _check_game_ok(session_id: str = "default") -> Dict[str, Any]:
    if not HANDLE_OBJ.is_alive():
        HANDLE_OBJ.refresh_handle()
        if not HANDLE_OBJ.is_alive():
            return _error("游戏未启动，请先启动游戏")
    # 将游戏窗口前置
    time.sleep(1) # 由于奇想盒前端会在任务开始时将自己最小化，而这里同时将游戏窗口前置，会导致windows窗口抢占，前置失败报错，所以加点延时
    HANDLE_OBJ.set_foreground()
    
    shape_ok, width, height = HANDLE_OBJ.check_shape()
    if not shape_ok:
        return _error("奇想盒只支持16:9与16:10的游戏分辨率")
    logger.info(f"游戏分辨率：{width}x{height}")
    if width > 2560 or width < 1920:
        msg = (
            f"❗当前游戏分辨率：{width}x{height}。"
            "推荐使用1920x1080或1920x1200或2560x1440或2560x1600分辨率，窗口模式。"
            "如遇到bug，请修改游戏分辨率和显示模式后重试\n"
        )
        notify_event(
            "event.run.log",
            {
                "session_id": session_id,
                "run_id": session_id,
                "source": "task",
                "message": msg,
                "raw_message": msg,
                "level": "info",
                "type": "update_ai_message",
            },
        )
        logger.info(msg)
    return {}


def _with_game_check(func):
    def wrapper(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        result = _check_game_ok(session_id=session_id)
        if result:
            return result
        return func(session_id, input, context)

    return wrapper

def _with_windows_notify(func):
    def wrapper(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        result = func(session_id, input, context)
        if isinstance(result, dict) and "message" in result:
            message = result.get("message", "")
            status = result.get("status", "")
            title = "奇想盒 - 任务完成" if status == STATE_TYPE_SUCCESS else "奇想盒 - 任务失败"
            try:
                send_notification(title=title, message=message, status=status)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"发送通知失败（不影响主功能）: {exc}")
        return result

    return wrapper


@_with_game_check
def run_jihua(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(JihuaTask, session_id, input, context)


@_with_game_check
def run_bless(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(BlessTask, session_id, input, context)


@_with_game_check
def run_monster(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    level_name = input.get("level_name")
    if level_name and len(level_name) > 2:
        return _error("魔物试炼幻境的关卡名，只需要输入最后两个字")
    return TaskAdapter.run(MonsterTask, session_id, input, context)


@_with_game_check
def run_dig(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(DigTaskV2, session_id, input, context)


@_with_game_check
def run_zhaoxi(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(ZhaoxiTask, session_id, input, context)


def run_search_path(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    name = input.get("name")
    target = input.get("target")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    target = target.strip() if isinstance(target, str) and target.strip() else None

    path_items = scripts_manager.search_path_items(
        name=name,
        target=target,
    )
    macro_items = []
    music_items = []
    if name:
        macro_items = scripts_manager.search_macro_items(
            name=name,
            is_play_music=False,
        )
        music_items = scripts_manager.search_macro_items(
            name=name,
            is_play_music=True,
        )

    # name/target 由大语言模型判断，偶尔会被放进错误的字段。
    # 保留首次查询的严格语义；只有找不到路线时，才让每个关键词分别匹配
    # 路线名和目标素材名，避免字段误判直接导致无结果。
    relaxed_search = False
    if not path_items and (name or target):
        keywords = list(dict.fromkeys(keyword for keyword in (name, target) if keyword))
        relaxed_path_items = []
        seen_path_names = set()

        for keyword in keywords:
            for search_kwargs in ({"name": keyword}, {"target": keyword}):
                for item in scripts_manager.search_path_items(**search_kwargs):
                    path_name = item.get("path_name")
                    if path_name in seen_path_names:
                        continue
                    seen_path_names.add(path_name)
                    relaxed_path_items.append(item)
                    if len(relaxed_path_items) >= 5:
                        break
                if len(relaxed_path_items) >= 5:
                    break
            if len(relaxed_path_items) >= 5:
                break

        if relaxed_path_items:
            path_items = relaxed_path_items
            relaxed_search = True

        # target 也可能实际是宏名或乐谱名；仅在首次路线查询失败时补查。
        if target and target != name:
            if not macro_items:
                macro_items = scripts_manager.search_macro_items(
                    name=target,
                    is_play_music=False,
                )
            if not music_items:
                music_items = scripts_manager.search_macro_items(
                    name=target,
                    is_play_music=True,
                )
            if macro_items or music_items:
                relaxed_search = True

    items = (
        [{"item_type": "path", **item} for item in path_items]
        + [{"item_type": "macro", **item} for item in macro_items]
        + [{"item_type": "music", **item} for item in music_items]
    )

    if not items:
        return {
            "status": STATE_TYPE_ERROR,
            "message": "没有找到符合条件的路线或宏",
            "items": [],
        }

    path_count = len(path_items)
    macro_count = len(macro_items)
    music_count = len(music_items)
    summary_parts = []
    if path_count:
        summary_parts.append(f"路线 {path_count} 条")
    if macro_count:
        summary_parts.append(f"宏 {macro_count} 条")
    if music_count:
        summary_parts.append(f"乐谱 {music_count} 条")

    message_prefix = "严格条件无匹配，已自动放宽关键词字段；" if relaxed_search else ""
    return {
        "status": STATE_TYPE_SUCCESS,
        "message": f"{message_prefix}已找到 {len(items)} 条候选脚本（{'，'.join(summary_parts)}）",
        "items": items,
    }


@_with_game_check
def run_load_path(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    path_name = input.get("path_name")
    if not path_name:
        return _error("路线名不能为空")
    path_record = scripts_manager.query_path(path_name=path_name, return_one=True)
    if path_record is None:
        return _error(f"路线\"{path_name}\"不存在")
    loop_overrides = input.get("loop_overrides")
    return TaskAdapter.run(
        AutoPathTask,
        session_id,
        {"path_record": path_record, "loop_overrides": loop_overrides},
        context,
    )


@_with_game_check
def run_record_path(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(RecordPathTask, session_id, {}, context)


@_with_game_check
def run_record_macro(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(RecordMacroTask, session_id, {}, context)


@_with_game_check
def run_run_macro(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    macro_name = input.get("macro_name")
    if not macro_name:
        return _error("宏名称不能为空")
    macro_record = scripts_manager.query_macro(macro_name, is_play_music=False, return_one=True)
    if macro_record is None:
        return _error(f"宏\"{macro_name}\"不存在")
    return TaskAdapter.run(RunMacroTask, session_id, {"macro_filename": macro_record.info.name}, context)


@_with_game_check
def run_play_music(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    music_name = input.get("music_name") or input.get("macro_name")
    if not music_name:
        return _error("乐谱名称不能为空")
    macro_record = scripts_manager.query_macro(music_name, is_play_music=True, return_one=True)
    if macro_record is None:
        return _error(f"乐谱\"{music_name}\"不存在")
    return TaskAdapter.run(RunMacroTask, session_id, {"macro_filename": macro_record.info.name}, context)


def run_open_path_folder(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    res, msg = scripts_manager.open_path_folder()
    return {
        "status": STATE_TYPE_SUCCESS if res else STATE_TYPE_ERROR,
        "message": msg,
    }


@_with_game_check
def run_daily_photo(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(DailyPhotoTask, session_id, input, context)


@_with_windows_notify
def run_all_in_one(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(AllInOneTask, session_id, input, context)


def run_start_game(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(StartGameTask, session_id, input, context)


@_with_game_check
def run_goto_ui(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(GotoUITask, session_id, input, context)


@_with_game_check
def run_monthly_pass(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(MonthlyPassTask, session_id, input, context)


@_with_game_check
def run_weekly_realm(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(WeeklyRealmTask, session_id, input, context)


@_with_game_check
def run_xinghai(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(XinghaiTask, session_id, input, context)


@_with_game_check
def run_mira_crown(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(MiraCrownTask, session_id, {"force_start": True}, context)


@_with_game_check
def run_xinghai_run(session_id: str, input: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return TaskAdapter.run(XinghaiRunTask, session_id, input, context)


TOOL_FUNCS = {
    "nikki.jihua": run_jihua,
    "nikki.bless": run_bless,
    "nikki.monster": run_monster,
    "nikki.dig": run_dig,
    "nikki.zhaoxi": run_zhaoxi,
    "nikki.search_path": run_search_path,
    "nikki.load_path": run_load_path,
    "nikki.record_path": run_record_path,
    "nikki.record_macro": run_record_macro,
    "nikki.run_macro": run_run_macro,
    "nikki.play_music": run_play_music,
    "nikki.open_path_folder": run_open_path_folder,
    "nikki.daily_photo": run_daily_photo,
    "nikki.all_in_one": run_all_in_one,
    "nikki.start_game": run_start_game,
    "nikki.goto_ui": run_goto_ui,
    "nikki.monthly_pass": run_monthly_pass,
    "nikki.weekly_realm": run_weekly_realm,
    "nikki.xinghai": run_xinghai,
    "nikki.mira_crown": run_mira_crown,
    "nikki.xinghai_run": run_xinghai_run,
}
