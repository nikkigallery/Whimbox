from __future__ import annotations

import os
import threading
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from whimbox.common.logger import logger
from whimbox.common.path_lib import SCRIPT_PATH
from whimbox.common.scripts_manager import scripts_manager
from whimbox.event_bus import emit_event


SCRIPT_REFRESH_DEBOUNCE_SECONDS = 0.3


def _is_json_path(path: str | bytes | None) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    return isinstance(path, str) and path.lower().endswith(".json")


class _ScriptEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ScriptsWatcher") -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in {"created", "modified", "deleted", "moved"}:
            return
        if not _is_json_path(event.src_path) and not _is_json_path(getattr(event, "dest_path", None)):
            return
        self._watcher.schedule_refresh()


class ScriptsWatcher:
    """监听脚本目录，并在文件事件停止一小段时间后统一刷新索引。"""

    def __init__(self, debounce_seconds: float = SCRIPT_REFRESH_DEBOUNCE_SECONDS) -> None:
        self._debounce_seconds = debounce_seconds
        self._lock = threading.Lock()
        self._observer: Optional[Observer] = None
        self._timer: Optional[threading.Timer] = None

    def start(self) -> None:
        with self._lock:
            if self._observer is not None:
                return
            os.makedirs(SCRIPT_PATH, exist_ok=True)
            observer = Observer()
            observer.schedule(_ScriptEventHandler(self), SCRIPT_PATH, recursive=True)
            observer.start()
            self._observer = observer
        logger.info(f"脚本目录监听已启动: {SCRIPT_PATH}")

    def stop(self) -> None:
        with self._lock:
            timer = self._timer
            observer = self._observer
            self._timer = None
            self._observer = None
        if timer is not None:
            timer.cancel()
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)

    def schedule_refresh(self) -> None:
        with self._lock:
            if self._observer is None:
                return
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(self._debounce_seconds, self._refresh)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _refresh(self) -> None:
        with self._lock:
            self._timer = None
            if self._observer is None:
                return
        try:
            snapshot = scripts_manager.init_scripts_dict()
            emit_event("event.scripts.changed", {**snapshot, "source": "watchdog"})
            logger.info(
                "脚本列表已自动刷新: "
                f"路线 {snapshot['path_count']}，宏 {snapshot['macro_count']}，乐谱 {snapshot['music_count']}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"自动刷新脚本列表失败: {exc}")


scripts_watcher = ScriptsWatcher()