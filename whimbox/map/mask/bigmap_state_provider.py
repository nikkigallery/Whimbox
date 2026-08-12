from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class BigMapDetectionState:
    is_bigmap_open: bool
    raw_is_bigmap_open: bool
    detection_mode: str
    detection_source: str
    detection_confidence: float
    detection_error: str
    last_detection_time: str
    last_successful_detection_time: str
    detection_duration_ms: float
    message: str = ""


class BigMapStateProvider:
    def __init__(self) -> None:
        self._last_successful_detection_time = ""
        self._last_auto_is_bigmap_open = False

    def get_mode(self) -> str:
        return "auto"

    def detect(self, captured_image=None) -> BigMapDetectionState:
        timestamp = datetime.now(tz=UTC).isoformat()
        started = time.perf_counter()
        source = "ui.page_assets.page_bigmap"
        confidence = 0.0
        error = ""
        message = "detected with page_bigmap check_icon"
        try:
            is_open = self._detect_with_whimbox_page(captured_image=captured_image)
            confidence = 0.85 if is_open else 0.65
            self._last_successful_detection_time = timestamp
            self._last_auto_is_bigmap_open = is_open
        except Exception as exc:  # noqa: BLE001
            source = "ui.page_assets.page_bigmap:error"
            error = str(exc)
            message = f"auto detection unavailable: {exc}"
            is_open = self._last_auto_is_bigmap_open
        return BigMapDetectionState(
            is_bigmap_open=is_open,
            raw_is_bigmap_open=is_open,
            detection_mode="auto",
            detection_source=source,
            detection_confidence=confidence,
            detection_error=error,
            last_detection_time=timestamp,
            last_successful_detection_time=self._last_successful_detection_time,
            detection_duration_ms=round((time.perf_counter() - started) * 1000, 2),
            message=message,
        )

    def _detect_with_whimbox_page(self, captured_image=None) -> bool:
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.page_assets import page_bigmap

        return bool(page_bigmap.is_current_page(itt, cap=captured_image))
