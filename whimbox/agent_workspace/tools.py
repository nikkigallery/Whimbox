from __future__ import annotations

import difflib
import json
import re
import shutil
import uuid
from threading import Event
from pathlib import Path

import cv2
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from typing_extensions import Literal


from whimbox.tool_invocation_coordinator import tool_invocation_coordinator
from whimbox.common.path_lib import LOG_PATH


SCREENSHOT_CACHE_DIR = Path(LOG_PATH) / "screenshot"


def get_screenshot_cache_dir() -> Path:
    SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_CACHE_DIR


def clear_screenshot_cache() -> None:
    screenshot_dir = get_screenshot_cache_dir()
    for entry in screenshot_dir.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError:
            continue


def _resolve_path(workspace_root: Path, path: str) -> Path:
    root = workspace_root.resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    resolved = target.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("path is outside agent workspace")
    return resolved


class ReadFileArgs(BaseModel):
    path: str = Field(..., description="要读取的 workspace 相对路径，例如 skills/memory/SKILL.md")


class WriteFileArgs(BaseModel):
    path: str = Field(..., description="要写入的 workspace 相对路径")
    content: str = Field(..., description="要写入文件的完整内容")


class EditFileArgs(BaseModel):
    path: str = Field(..., description="要编辑的 workspace 相对路径")
    old_text: str = Field(..., description="需要被替换的原始文本，必须完全匹配")
    new_text: str = Field(..., description="替换后的新文本")


class ListDirArgs(BaseModel):
    path: str = Field(..., description="要查看的 workspace 相对目录路径")


class GrepHistoryArgs(BaseModel):
    query: str = Field(..., description="要在 memory/HISTORY.md 中搜索的关键词或正则表达式")
    case_sensitive: bool = Field(False, description="是否区分大小写")
    regex: bool = Field(False, description="是否将 query 按正则表达式处理")
    max_results: int = Field(10, description="最多返回多少条匹配结果")


class AnalyzeImageArgs(BaseModel):
    mode: Literal["path", "screenshot"] = Field(..., description="使用 'path' 分析本地图片，或使用 'screenshot' 先截取当前游戏画面")
    prompt: str = Field(..., description="对图片执行的分析要求")
    path: str | None = Field(None, description="当 mode 为 'path' 时使用的本地图片绝对路径")


def build_workspace_tools(
    workspace_root: Path,
    *,
    session_id_getter=None,
    stop_event_getter=None,
    image_analyzer=None,
) -> list[StructuredTool]:
    def _invoke_serialized(func, *args, resource_group: str = "workspace_fs", owner_suffix: str = "workspace_fs", **kwargs):
        session_id = session_id_getter() if callable(session_id_getter) else "default"
        if not session_id:
            session_id = "default"
        stop_event = stop_event_getter() if callable(stop_event_getter) else None
        if not isinstance(stop_event, Event):
            stop_event = None
        owner = f"agent:{session_id}:{owner_suffix}"
        with tool_invocation_coordinator.hold_sync(
            resource_group=resource_group,
            owner=owner,
            wait_policy="wait",
            stop_event=stop_event,
        ) as acquire_result:
            if not acquire_result.acquired:
                if acquire_result.reason == "stopped":
                    return "Task stopped before operation started."
                return "Resource is busy. Try again after the current operation finishes."
            return func(*args, **kwargs)

    def _read_file(path: str) -> str:
        def _do_read() -> str:
            target = _resolve_path(workspace_root, path)
            if not target.exists():
                raise FileNotFoundError(path)
            if not target.is_file():
                raise ValueError("path must be a file")
            return target.read_text(encoding="utf-8")

        return _invoke_serialized(_do_read, resource_group="workspace_fs", owner_suffix="workspace_fs")

    def _write_file(path: str, content: str) -> str:
        def _do_write() -> str:
            target = _resolve_path(workspace_root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} chars to {target}"

        return _invoke_serialized(_do_write, resource_group="workspace_fs", owner_suffix="workspace_fs")

    def _edit_file(path: str, old_text: str, new_text: str) -> str:
        def _do_edit() -> str:
            target = _resolve_path(workspace_root, path)
            if not target.exists():
                raise FileNotFoundError(path)
            if not target.is_file():
                raise ValueError("path must be a file")

            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return _not_found_message(path, old_text, content)

            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times in {path}. Provide a more specific snippet."

            target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Successfully edited {target}"

        return _invoke_serialized(_do_edit, resource_group="workspace_fs", owner_suffix="workspace_fs")

    def _list_dir(path: str) -> str:
        def _do_list() -> str:
            target = _resolve_path(workspace_root, path)
            if not target.exists():
                raise FileNotFoundError(path)
            if not target.is_dir():
                raise ValueError("path must be a directory")
            items = [f"{'[dir]' if item.is_dir() else '[file]'} {item.name}" for item in sorted(target.iterdir())]
            return "\n".join(items) if items else f"Directory {path} is empty"

        return _invoke_serialized(_do_list, resource_group="workspace_fs", owner_suffix="workspace_fs")

    def _grep_history(
        query: str,
        case_sensitive: bool = False,
        regex: bool = False,
        max_results: int = 10,
    ) -> str:
        def _do_grep() -> str:
            history_path = workspace_root / "memory" / "HISTORY.md"
            if not history_path.exists():
                return "memory/HISTORY.md does not exist yet."

            content = history_path.read_text(encoding="utf-8")
            if not content.strip():
                return "memory/HISTORY.md is empty."

            lines = content.splitlines()
            limit = max(1, min(int(max_results), 50))
            matches: list[str] = []

            if regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(query, flags)
                for index, line in enumerate(lines, start=1):
                    if pattern.search(line):
                        matches.append(f"{index}: {line}")
                        if len(matches) >= limit:
                            break
            else:
                needle = query if case_sensitive else query.lower()
                for index, line in enumerate(lines, start=1):
                    haystack = line if case_sensitive else line.lower()
                    if needle in haystack:
                        matches.append(f"{index}: {line}")
                        if len(matches) >= limit:
                            break

            if not matches:
                return f'No matches found in memory/HISTORY.md for "{query}".'
            return "\n".join(matches)

        return _invoke_serialized(_do_grep, resource_group="workspace_fs", owner_suffix="workspace_fs")

    def _analyze_image(mode: str, prompt: str, path: str | None = None) -> str:
        if image_analyzer is None:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Image analysis is unavailable.",
                    "analysis": "",
                },
                ensure_ascii=False,
            )

        session_id = session_id_getter() if callable(session_id_getter) else "default"
        resource_group = "game_runtime" if mode == "screenshot" else "default"
        owner_suffix = "image_screenshot" if mode == "screenshot" else "image_analysis"

        def _do_analyze() -> str:
            resolved_path = path
            if mode == "screenshot":
                screenshot_dir = get_screenshot_cache_dir()
                screenshot_path = screenshot_dir / f"{session_id or 'default'}_{uuid.uuid4().hex}.png"
                try:
                    from whimbox.interaction.interaction_core import itt
                    image = itt.capture()
                    cv2.imwrite(str(screenshot_path), image)
                    resolved_path = str(screenshot_path)
                except Exception as e:
                    return json.dumps(
                        {
                            "status": "error",
                            "message": "无所对游戏截屏，游戏可能未启动",
                            "analysis": "",
                        },
                        ensure_ascii=False,
                    )
                
            if mode == "path":
                if not resolved_path:
                    raise ValueError("path is required when mode is 'path'")
                target = Path(resolved_path).expanduser()
                if not target.exists() or not target.is_file():
                    raise FileNotFoundError(resolved_path)
                resolved_path = str(target.resolve())
            result = image_analyzer(
                image_path=str(resolved_path or ""),
                prompt=prompt,
                session_id=session_id or "default",
                source_mode=mode,
            )
            return json.dumps(result, ensure_ascii=False)

        return _invoke_serialized(
            _do_analyze,
            resource_group=resource_group,
            owner_suffix=owner_suffix,
        )

    return [
        StructuredTool.from_function(
            func=_read_file,
            name="read_file",
            description="读取 agent workspace 中的文本文件，例如 SKILL.md 或 MEMORY.md。",
            args_schema=ReadFileArgs,
        ),
        StructuredTool.from_function(
            func=_write_file,
            name="write_file",
            description="向 agent workspace 中的文件写入完整内容。",
            args_schema=WriteFileArgs,
        ),
        StructuredTool.from_function(
            func=_edit_file,
            name="edit_file",
            description="编辑 agent workspace 中的文件，将完全匹配的 old_text 替换为 new_text。",
            args_schema=EditFileArgs,
        ),
        StructuredTool.from_function(
            func=_list_dir,
            name="list_dir",
            description="列出 agent workspace 中指定目录下的文件和子目录。",
            args_schema=ListDirArgs,
        ),
        StructuredTool.from_function(
            func=_grep_history,
            name="grep_history",
            description="搜索 memory/HISTORY.md 中的旧归档内容。当需要查找未加载到上下文中的较早对话历史时使用。",
            args_schema=GrepHistoryArgs,
        ),
        StructuredTool.from_function(
            func=_analyze_image,
            name="analyze_image",
            description="图像分析工具，此工具只会被skill调用，不要擅自调用",
            args_schema=AnalyzeImageArgs,
        ),
    ]


def _not_found_message(path: str, old_text: str, content: str) -> str:
    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = max(len(old_lines), 1)

    best_ratio = 0.0
    best_start = 0
    for index in range(max(1, len(lines) - window + 1)):
        candidate = lines[index : index + window]
        ratio = difflib.SequenceMatcher(None, old_lines, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = index

    if best_ratio > 0.5:
        diff = "\n".join(
            difflib.unified_diff(
                old_lines,
                lines[best_start : best_start + window],
                fromfile="old_text (provided)",
                tofile=f"{path} (actual, line {best_start + 1})",
                lineterm="",
            )
        )
        return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
    return f"Error: old_text not found in {path}. No similar text found."
