from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from whimbox.common.logger import logger
from whimbox.common.timer_module import Timer
from whimbox.common.utils.img_utils import rgb2luma
from whimbox.map.detection.cvars import (
    MINIMAP_CENTER,
    MINIMAP_POSITION_RADIUS,
    MINIMAP_POSITION_SCALE_DICT,
    MINIMAP_RADIUS,
)

from .models import MapMaskViewport


_MINIMAP_UPDATE_INTERVAL_SECONDS = 0.02
_MINIMAP_CONFIDENCE_THRESHOLD = 0.25
_MINIMAP_FAILURE_LIMIT = 5
_UNINITIALIZED_HINT = "请打开大地图完成小地图定位"
_LOST_HINT = "小地图定位已失效，请打开大地图重新定位"


@dataclass(slots=True)
class MiniMapTrackingSnapshot:
    status: str
    is_main_world_open: bool
    map_name: str
    position_x: float | None
    position_y: float | None
    confidence: float
    local_confidence: float
    failure_count: int
    hint: str
    viewport: MapMaskViewport | None
    screen_width: int | None
    screen_height: int | None


class MiniMapPositionTracker:
    """Track the player with the existing local minimap matcher.

    The first position is deliberately supplied by the big-map detector. This
    keeps the existing nearby-search algorithm passive: it never opens or
    operates the game UI on its own.
    """

    def __init__(self, detector: Any | None = None) -> None:
        self._detector = detector
        self._status = "uninitialized"
        self._map_name = ""
        self._confidence = 0.0
        self._local_confidence = 0.0
        self._failure_count = 0
        self._last_update_monotonic = 0.0

    @property
    def needs_calibration(self) -> bool:
        return self._status in {"uninitialized", "lost"}

    @property
    def status(self) -> str:
        return self._status

    def initialize(self, position: tuple[float, float], map_name: str) -> bool:
        if map_name not in MINIMAP_POSITION_SCALE_DICT:
            logger.warning(
                f"[map-mask-minimap] unsupported map for tracking: {map_name}"
            )
            return False
        detector = self._ensure_detector()
        detector.map_name = map_name
        detector.init_position(tuple(float(value) for value in position))
        # The first local match is allowed to correct the big-map seed without
        # being rejected by the movement-speed guard.
        detector.pos_change_timer = Timer(diff_start_time=30)
        self._map_name = map_name
        self._status = "tracking"
        self._confidence = 1.0
        self._local_confidence = 1.0
        self._failure_count = 0
        self._last_update_monotonic = 0.0
        logger.info(
            "[map-mask-minimap] calibrated "
            f"map={map_name} position=({position[0]:.1f},{position[1]:.1f})"
        )
        return True

    def update(
        self,
        captured_image: Any,
        *,
        is_main_world_open: bool,
    ) -> MiniMapTrackingSnapshot:
        screen_width, screen_height = _image_size(captured_image)
        if not is_main_world_open or self._status != "tracking":
            return self.snapshot(
                is_main_world_open=is_main_world_open,
                screen_width=screen_width,
                screen_height=screen_height,
            )

        now = time.monotonic()
        if now - self._last_update_monotonic < _MINIMAP_UPDATE_INTERVAL_SECONDS:
            return self.snapshot(
                is_main_world_open=True,
                screen_width=screen_width,
                screen_height=screen_height,
            )
        self._last_update_monotonic = now

        try:
            detector = self._ensure_detector()
            minimap = detector._get_minimap(
                captured_image,
                MINIMAP_POSITION_RADIUS,
            )
            minimap = rgb2luma(minimap)

            confidence, local_confidence, candidate = detector._predict_position(
                minimap,
                MINIMAP_POSITION_SCALE_DICT[self._map_name],
            )
            self._confidence = round(float(confidence), 5)
            self._local_confidence = round(float(local_confidence), 5)
            candidate_position = tuple(np.round(candidate, 1))
            if self._confidence < _MINIMAP_CONFIDENCE_THRESHOLD:
                self._record_failure(
                    f"confidence {self._confidence:.3f} below "
                    f"{_MINIMAP_CONFIDENCE_THRESHOLD:.3f}"
                )
            elif not detector.verify_position(candidate_position):
                self._record_failure("position movement verification failed")
            else:
                detector.position = candidate_position
                self._failure_count = 0
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"{type(exc).__name__}: {exc}")

        return self.snapshot(
            is_main_world_open=True,
            screen_width=screen_width,
            screen_height=screen_height,
        )

    def snapshot(
        self,
        *,
        is_main_world_open: bool,
        screen_width: int | None,
        screen_height: int | None,
    ) -> MiniMapTrackingSnapshot:
        position = self._position()
        viewport = None
        if self._status == "tracking" and position is not None:
            viewport = _minimap_viewport(
                position=position,
                map_name=self._map_name,
            )
        hint = ""
        if is_main_world_open:
            if self._status == "uninitialized":
                hint = _UNINITIALIZED_HINT
            elif self._status == "lost":
                hint = _LOST_HINT
        return MiniMapTrackingSnapshot(
            status=self._status,
            is_main_world_open=is_main_world_open,
            map_name=self._map_name,
            position_x=position[0] if position is not None else None,
            position_y=position[1] if position is not None else None,
            confidence=self._confidence,
            local_confidence=self._local_confidence,
            failure_count=self._failure_count,
            hint=hint,
            viewport=viewport,
            screen_width=screen_width,
            screen_height=screen_height,
        )

    def _ensure_detector(self):
        if self._detector is None:
            from whimbox.map.detection.minimap import MiniMap

            self._detector = MiniMap()
        return self._detector

    def _position(self) -> tuple[float, float] | None:
        if self._detector is None or self._status != "tracking":
            return None
        position = self._detector.position
        return float(position[0]), float(position[1])

    def _record_failure(self, reason: str) -> None:
        self._failure_count += 1
        if self._failure_count < _MINIMAP_FAILURE_LIMIT:
            return
        self._status = "lost"
        logger.warning(
            "[map-mask-minimap] tracking lost "
            f"confidence={self._confidence:.3f} "
            f"local={self._local_confidence:.3f} reason={reason}"
        )

def _minimap_viewport(
    *,
    position: tuple[float, float],
    map_name: str,
) -> MapMaskViewport:
    scale = MINIMAP_POSITION_SCALE_DICT[map_name]
    image_radius = MINIMAP_RADIUS * scale
    return MapMaskViewport(
        map_name=map_name,
        image_left=position[0] - image_radius,
        image_top=position[1] - image_radius,
        image_width=image_radius * 2,
        image_height=image_radius * 2,
        screen_left=MINIMAP_CENTER[0] - MINIMAP_RADIUS,
        screen_top=MINIMAP_CENTER[1] - MINIMAP_RADIUS,
        screen_width=MINIMAP_RADIUS * 2,
        screen_height=MINIMAP_RADIUS * 2,
        scale=scale,
    )


def _image_size(image: Any) -> tuple[int | None, int | None]:
    shape = getattr(image, "shape", None)
    if shape is None or len(shape) < 2:
        return None, None
    return int(shape[1]), int(shape[0])
