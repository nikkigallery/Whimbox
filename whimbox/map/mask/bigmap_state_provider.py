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
    detection_mode: BigMapDetectionMode
    detection_source: str
    detection_confidence: float
    detection_error: str
    last_detection_time: str
    last_successful_detection_time: str
    detection_duration_ms: float
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BigMapStateProvider:
    def __init__(self) -> None:
        self._manual_mode: BigMapDetectionMode = _initial_detection_mode()
        self._last_successful_detection_time = ""
        self._last_auto_is_bigmap_open = False

    def get_mode(self) -> BigMapDetectionMode:
        return _env_detection_mode() or self._manual_mode

    def set_mode(self, mode: str) -> BigMapDetectionMode:
        normalized = _normalize_detection_mode(mode)
        if normalized != self._manual_mode:
            self._reset_auto_state()
            self._manual_mode = normalized
        return normalized

    def detect(self, captured_image=None) -> BigMapDetectionState:
        mode = self.get_mode()
        timestamp = _now()

        if mode == "force-open":
            return BigMapDetectionState(
                is_bigmap_open=True,
                raw_is_bigmap_open=True,
                detection_mode=mode,
                detection_source="manual.force-open",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time=timestamp,
                last_successful_detection_time=timestamp,
                detection_duration_ms=0.0,
                message="big map forced open",
            )

        if mode == "force-closed":
            return BigMapDetectionState(
                is_bigmap_open=False,
                raw_is_bigmap_open=False,
                detection_mode=mode,
                detection_source="manual.force-closed",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time=timestamp,
                last_successful_detection_time=timestamp,
                detection_duration_ms=0.0,
                message="big map forced closed",
            )

        return self._detect_auto(timestamp, captured_image=captured_image)

    def _detect_auto(self, timestamp: str, captured_image=None) -> BigMapDetectionState:
        started = time.perf_counter()
        raw_is_open = False
        source = "ui.page_assets.page_bigmap"
        confidence = 0.0
        error = ""
        message = "detected with page_bigmap check_icon"

        try:
            raw_is_open = self._detect_with_whimbox_page(captured_image=captured_image)
            confidence = 0.85 if raw_is_open else 0.65
            self._last_successful_detection_time = timestamp
            self._last_auto_is_bigmap_open = raw_is_open
        except Exception as exc:  # noqa: BLE001
            source = "ui.page_assets.page_bigmap:error"
            error = str(exc)
            message = f"auto detection unavailable: {exc}"
            raw_is_open = self._last_auto_is_bigmap_open

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        state = BigMapDetectionState(
            is_bigmap_open=raw_is_open,
            raw_is_bigmap_open=raw_is_open,
            detection_mode="auto",
            detection_source=source,
            detection_confidence=confidence,
            detection_error=error,
            last_detection_time=timestamp,
            last_successful_detection_time=self._last_successful_detection_time,
            detection_duration_ms=duration_ms,
            message=message,
        )
        self._debug_log(state)
        return state

    def _detect_with_whimbox_page(self, captured_image=None) -> bool:
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.page_assets import page_bigmap

        return bool(page_bigmap.is_current_page(itt, cap=captured_image))

    def _reset_auto_state(self) -> None:
        self._last_successful_detection_time = ""
        self._last_auto_is_bigmap_open = False

    def _debug_log(self, state: BigMapDetectionState) -> None:
        if not _is_truthy(os.environ.get("WHIMBOX_MAP_MASK_DEBUG_DETECTION")):
            return
        logger.info(
            "[map-mask-detection] "
            f"mode={state.detection_mode} raw={state.raw_is_bigmap_open} "
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


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
