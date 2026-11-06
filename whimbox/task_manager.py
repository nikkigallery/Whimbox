from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from whimbox.common.cvars import reset_task_pause


@dataclass
class TaskInfo:
    task_id: str
    session_id: str
    tool_id: str
    state: str = "PENDING"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    stop_event: Event = field(default_factory=Event, repr=False)
    asyncio_task: Optional[Any] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "tool_id": self.tool_id,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class TaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = Lock()

    def create(self, session_id: str, tool_id: str) -> TaskInfo:
        task_id = f"task_{uuid4().hex}"
        task = TaskInfo(task_id=task_id, session_id=session_id, tool_id=tool_id)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.to_dict() if task else None

    def set_state(
        self,
        task_id: str,
        state: str,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.state = state
            if state == "RUNNING":
                task.started_at = datetime.now(timezone.utc).isoformat()
            if state in {"SUCCESS", "ERROR", "CANCELLED"}:
                task.finished_at = datetime.now(timezone.utc).isoformat()
            task.error = error
            task.result = result
            return task.to_dict()

    def attach_asyncio_task(self, task_id: str, asyncio_task: Any) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.asyncio_task = asyncio_task

    def stop(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.stop_event.set()
            reset_task_pause()
            return True

    def stop_all(self) -> list[Dict[str, Any]]:
        stopped: list[Dict[str, Any]] = []
        with self._lock:
            for task in self._tasks.values():
                if task.state in {"PENDING", "RUNNING"}:
                    task.stop_event.set()
                    stopped.append(task.to_dict())
        if stopped:
            reset_task_pause()
        return stopped

    def has_active(self, session_id: str | None = None) -> bool:
        with self._lock:
            for task in self._tasks.values():
                if task.state not in {"PENDING", "RUNNING"}:
                    continue
                if session_id is not None and task.session_id != session_id:
                    continue
                return True
        return False

    def get_active_for_session(self, session_id: str) -> list[Dict[str, Any]]:
        active: list[Dict[str, Any]] = []
        with self._lock:
            for task in self._tasks.values():
                if task.session_id != session_id:
                    continue
                if task.state not in {"PENDING", "RUNNING"}:
                    continue
                active.append(task.to_dict())
        active.sort(
            key=lambda item: str(item.get("started_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return active

    def get_active(self) -> list[Dict[str, Any]]:
        with self._lock:
            return [
                task.to_dict()
                for task in self._tasks.values()
                if task.state in {"PENDING", "RUNNING"}
            ]

    def stop_active_for_session(self, session_id: str) -> list[Dict[str, Any]]:
        stopped: list[Dict[str, Any]] = []
        with self._lock:
            for task in self._tasks.values():
                if task.session_id != session_id:
                    continue
                if task.state not in {"PENDING", "RUNNING"}:
                    continue
                task.stop_event.set()
                stopped.append(task.to_dict())
        if stopped:
            reset_task_pause()
        return stopped


task_manager = TaskManager()
