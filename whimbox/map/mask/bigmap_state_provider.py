from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from whimbox.common.logger import logger


BigMapDetectionMode = Literal["auto", "force-open", "force-closed"]


@dataclass(slots=True)
class BigMapDetectionState:
    is_bigmap_open: bool
    raw_is_bigmap_open: bool
    stable_is_bigmap_open: bool
    consecutive_open_count: int
    consecutive_closed_count: int
    detection_mode: BigMapDetectionMode
    detection_source: str
    detection_confidence: float
    detection_error: str
    last_detection_time: str
    last_successful_detection_time: str
    detection_duration_ms: float
    detection_interval_ms: int
    stable_open_frames: int
    stable_closed_frames: int
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BigMapStateProvider:
    def __init__(self) -> None:
        self._manual_mode: BigMapDetectionMode = _initial_detection_mode()
        self._detection_interval_ms = _env_int(
            "WHIMBOX_MAP_MASK_DETECTION_INTERVAL_MS",
            default=100,
            minimum=100,
        )
        stable_frames = _env_int(
            "WHIMBOX_MAP_MASK_STABLE_FRAMES",
            default=2,
            minimum=1,
        )
        self._stable_open_frames = _env_int(
            "WHIMBOX_MAP_MASK_STABLE_OPEN_FRAMES",
            default=stable_frames,
            minimum=1,
        )
        self._stable_closed_frames = _env_int(
            "WHIMBOX_MAP_MASK_STABLE_CLOSED_FRAMES",
            default=stable_frames,
            minimum=1,
        )
        self._cached_auto_state: BigMapDetectionState | None = None
        self._last_detection_monotonic = 0.0
        self._last_successful_detection_time = ""
        self._raw_is_bigmap_open = False
        self._stable_is_bigmap_open = False
        self._consecutive_open_count = 0
        self._consecutive_closed_count = 0

    def get_mode(self) -> BigMapDetectionMode:
        return _env_detection_mode() or self._manual_mode

    def set_mode(self, mode: str) -> BigMapDetectionMode:
        normalized = _normalize_detection_mode(mode)
        if normalized != self._manual_mode:
            self._reset_auto_state()
            self._manual_mode = normalized
        return normalized

    def detect(self) -> BigMapDetectionState:
        mode = self.get_mode()
        timestamp = _now()

        if mode == "force-open":
            return BigMapDetectionState(
                is_bigmap_open=True,
                raw_is_bigmap_open=True,
                stable_is_bigmap_open=True,
                consecutive_open_count=self._stable_open_frames,
                consecutive_closed_count=0,
                detection_mode=mode,
                detection_source="manual.force-open",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time=timestamp,
                last_successful_detection_time=timestamp,
                detection_duration_ms=0.0,
                detection_interval_ms=self._detection_interval_ms,
                stable_open_frames=self._stable_open_frames,
                stable_closed_frames=self._stable_closed_frames,
                message="big map forced open",
            )

        if mode == "force-closed":
            return BigMapDetectionState(
                is_bigmap_open=False,
                raw_is_bigmap_open=False,
                stable_is_bigmap_open=False,
                consecutive_open_count=0,
                consecutive_closed_count=self._stable_closed_frames,
                detection_mode=mode,
                detection_source="manual.force-closed",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time=timestamp,
                last_successful_detection_time=timestamp,
                detection_duration_ms=0.0,
                detection_interval_ms=self._detection_interval_ms,
                stable_open_frames=self._stable_open_frames,
                stable_closed_frames=self._stable_closed_frames,
                message="big map forced closed",
            )

        return self._detect_auto(timestamp)

    def _detect_auto(self, timestamp: str) -> BigMapDetectionState:
        now = time.monotonic()
        if (
            self._cached_auto_state is not None
            and (now - self._last_detection_monotonic) * 1000 < self._detection_interval_ms
        ):
            return self._cached_auto_state

        started = time.perf_counter()
        raw_is_open = False
        source = "ui.page_assets.page_bigmap"
        confidence = 0.0
        error = ""
        message = "detected with page_bigmap check_icon"

        try:
            raw_is_open = self._detect_with_whimbox_page()
            confidence = 0.85 if raw_is_open else 0.65
            self._last_successful_detection_time = timestamp
            self._apply_stable_frame(raw_is_open)
        except Exception as exc:  # noqa: BLE001
            source = "ui.page_assets.page_bigmap:error"
            error = str(exc)
            message = f"auto detection unavailable: {exc}"
            raw_is_open = self._raw_is_bigmap_open

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        state = BigMapDetectionState(
            is_bigmap_open=self._stable_is_bigmap_open,
            raw_is_bigmap_open=raw_is_open,
            stable_is_bigmap_open=self._stable_is_bigmap_open,
            consecutive_open_count=self._consecutive_open_count,
            consecutive_closed_count=self._consecutive_closed_count,
            detection_mode="auto",
            detection_source=source,
            detection_confidence=confidence,
            detection_error=error,
            last_detection_time=timestamp,
            last_successful_detection_time=self._last_successful_detection_time,
            detection_duration_ms=duration_ms,
            detection_interval_ms=self._detection_interval_ms,
            stable_open_frames=self._stable_open_frames,
            stable_closed_frames=self._stable_closed_frames,
            message=message,
        )
        self._cached_auto_state = state
        self._last_detection_monotonic = now
        self._debug_log(state)
        return state

    def _detect_with_whimbox_page(self) -> bool:
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.page_assets import page_bigmap

        return bool(page_bigmap.is_current_page(itt))

    def _apply_stable_frame(self, raw_is_open: bool) -> None:
        self._raw_is_bigmap_open = raw_is_open
        if raw_is_open:
            self._consecutive_open_count += 1
            self._consecutive_closed_count = 0
            if self._consecutive_open_count >= self._stable_open_frames:
                self._stable_is_bigmap_open = True
            return

        self._consecutive_closed_count += 1
        self._consecutive_open_count = 0
        if self._consecutive_closed_count >= self._stable_closed_frames:
            self._stable_is_bigmap_open = False

    def _reset_auto_state(self) -> None:
        self._cached_auto_state = None
        self._last_detection_monotonic = 0.0
        self._last_successful_detection_time = ""
        self._raw_is_bigmap_open = False
        self._stable_is_bigmap_open = False
        self._consecutive_open_count = 0
        self._consecutive_closed_count = 0

    def _debug_log(self, state: BigMapDetectionState) -> None:
        if not _is_truthy(os.environ.get("WHIMBOX_MAP_MASK_DEBUG_DETECTION")):
            return
        logger.info(
            "[map-mask-detection] "
            f"mode={state.detection_mode} raw={state.raw_is_bigmap_open} "
            f"stable={state.stable_is_bigmap_open} "
            f"open_count={state.consecutive_open_count} "
            f"closed_count={state.consecutive_closed_count} "
            f"confidence={state.detection_confidence:.2f} "
            f"duration_ms={state.detection_duration_ms:.2f} "
            f"source={state.detection_source} "
            f"error={state.detection_error}"
        )


def _initial_detection_mode() -> BigMapDetectionMode:
    return _env_detection_mode() or "auto"


def _env_detection_mode() -> BigMapDetectionMode | None:
    if _is_truthy(os.environ.get("WHIMBOX_MAP_MASK_FORCE_BIGMAP_OPEN")):
        return "force-open"
    if _is_truthy(os.environ.get("WHIMBOX_MAP_MASK_FORCE_BIGMAP_CLOSED")):
        return "force-closed"
    if _is_truthy(os.environ.get("WHIMBOX_MAP_MASK_SMOKE")):
        return "force-open"

    raw_mode = os.environ.get("WHIMBOX_MAP_MASK_BIGMAP_DETECTION_MODE")
    if not raw_mode:
        return None
    return _normalize_detection_mode(raw_mode)


def _normalize_detection_mode(mode: str) -> BigMapDetectionMode:
    normalized = mode.strip().lower().replace("_", "-")
    if normalized in {"open", "force-open", "forced-open"}:
        return "force-open"
    if normalized in {"closed", "close", "force-closed", "forced-closed"}:
        return "force-closed"
    if normalized in {"auto", "detect", "auto-detect"}:
        return "auto"
    raise ValueError("mode must be one of: auto, force-open, force-closed")


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return max(minimum, value)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
