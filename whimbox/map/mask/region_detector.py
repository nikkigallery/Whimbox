from __future__ import annotations

import time
from typing import Any

from whimbox.common.logger import logger
from whimbox.map.detection.cvars import (
    BIGMAP_POSITION_SCALE_DICT,
    MAP_NAME_MIRALAND,
    REGION_NAME_TO_MAP_NAME_DICT,
)


_REGION_RETRY_INTERVAL_SECONDS = 0.5


class BigMapRegionDetector:
    """Resolve the active map from the region name already visible in Big Map."""

    def __init__(self) -> None:
        self._map_name = MAP_NAME_MIRALAND
        self._region_name = ""
        self._last_bigmap_open = False
        self._refresh_requested = True
        self._last_attempt_monotonic = 0.0
        self._last_unrecognized_text = ""

    @property
    def map_name(self) -> str:
        return self._map_name

    @property
    def region_name(self) -> str:
        return self._region_name

    def request_refresh(self) -> None:
        self._refresh_requested = True

    def confirm_current_map(self) -> None:
        """Keep the cached map after a successful viewport match."""
        self._last_bigmap_open = True
        self._refresh_requested = False

    def update(
        self,
        captured_image: Any,
        *,
        is_bigmap_open: bool,
        requested_map_name: str | None = None,
    ) -> tuple[str, bool]:
        if requested_map_name:
            changed = requested_map_name != self._map_name
            self._map_name = requested_map_name
            self._last_bigmap_open = bool(is_bigmap_open)
            return self._map_name, changed

        if not is_bigmap_open:
            self._last_bigmap_open = False
            return self._map_name, False

        just_opened = not self._last_bigmap_open
        self._last_bigmap_open = True
        if not just_opened and not self._refresh_requested:
            return self._map_name, False

        now = time.monotonic()
        if (
            not just_opened
            and now - self._last_attempt_monotonic
            < _REGION_RETRY_INTERVAL_SECONDS
        ):
            return self._map_name, False
        self._last_attempt_monotonic = now
        self._refresh_requested = False

        try:
            region_text = _ocr_region_name(captured_image)
        except Exception as exc:  # noqa: BLE001
            self._refresh_requested = True
            logger.warning(
                "[map-mask-region] region OCR failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return self._map_name, False

        region_name = _match_region_name(region_text)
        if region_name is None:
            self._refresh_requested = True
            if region_text != self._last_unrecognized_text:
                logger.warning(
                    "[map-mask-region] unrecognized big-map region: "
                    f"text={region_text!r}"
                )
                self._last_unrecognized_text = region_text
            return self._map_name, False

        map_name = _map_name_for_region(region_name)
        if map_name not in BIGMAP_POSITION_SCALE_DICT:
            self._refresh_requested = True
            return self._map_name, False

        previous_map_name = self._map_name
        self._map_name = map_name
        self._region_name = region_name
        self._last_unrecognized_text = ""
        changed = map_name != previous_map_name
        if changed:
            logger.info(
                "[map-mask-region] active map changed: "
                f"region={region_name}, map={previous_map_name}->{map_name}"
            )
        return map_name, changed


def _ocr_region_name(captured_image: Any) -> str:
    from whimbox.interaction.interaction_core import itt
    from whimbox.ui.ui_assets import AreaBigMapRegionName

    return itt.ocr_single_line(
        AreaBigMapRegionName,
        padding=50,
        hsv_limit=([0, 0, 0], [180, 255, 180]),
        cap=captured_image,
    ).strip()


def _match_region_name(raw_text: str) -> str | None:
    compact = "".join(str(raw_text or "").split())
    if not compact:
        return None
    region_names = (
        region_name
        for names in REGION_NAME_TO_MAP_NAME_DICT.values()
        for region_name in names
    )
    for region_name in region_names:
        if compact == region_name or region_name in compact:
            return region_name
    return None


def _map_name_for_region(region_name: str) -> str:
    for map_name, region_names in REGION_NAME_TO_MAP_NAME_DICT.items():
        if region_name in region_names:
            return map_name
    return ""
