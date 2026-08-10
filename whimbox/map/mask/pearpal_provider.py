from __future__ import annotations

import math
import threading
from typing import Any

from whimbox.common.logger import logger

from .models import MapMaskLabel, MapMaskPoint
from .pearpal_debug import (
    PearPalPublicDebugClient,
    expand_stage_spawners,
    flatten_catalogs,
    localized_text,
    spawner_catalog_id,
    spawner_stage_id,
    spawner_world_id,
)


_WORLD_ID = "1"
_MAP_NAME = "miraland"
_BOX_CATALOG_GROUP_ID = "14"
# Public catalogs used for Whimstar variants in the currently known worlds.
# World 1 currently resolves to catalog 11; keeping the complete known set here
# makes the classification explicit when more world transforms are added.
_STAR_CATALOG_IDS = frozenset({"11", "132", "145", "167", "244"})

# The refreshed public world-1 coordinates use the same standard 2/90 scale as
# the Whimbox full-resolution map and no additional web-map origin offset.
_MIRALAND_SCALE_X = 2 / 90
_MIRALAND_OFFSET_X = 0.0
_MIRALAND_SCALE_Y = 2 / 90
_MIRALAND_OFFSET_Y = 0.0

_STAR_LABEL = MapMaskLabel(
    id="pearpal_star",
    name="奇想星",
    provider="pearpal",
    default_enabled=True,
)
_BOX_LABEL = MapMaskLabel(
    id="pearpal_box",
    name="宝箱",
    provider="pearpal",
    default_enabled=True,
)


class OfficialPearPalProvider:
    """Anonymous PearPal public point provider.

    Loading starts lazily on the first overlay request. Production callers use
    a daemon thread so public API latency never blocks the 50 ms overlay poll.
    Authentication and per-user awarded-state filtering intentionally live
    outside this first anonymous implementation.
    """

    name = "pearpal"

    def __init__(
        self,
        enabled: bool = False,
        *,
        client: Any | None = None,
        background: bool = True,
        language: str = "zh-cn",
    ) -> None:
        self.enabled = enabled
        self._client = client or PearPalPublicDebugClient(language=language)
        self._background = background
        self._language = language
        self._lock = threading.RLock()
        self._load_state = "idle"
        self._load_error = ""
        self._points: tuple[MapMaskPoint, ...] = ()
        self._point_by_id: dict[str, MapMaskPoint] = {}

    def list_labels(self) -> list[MapMaskLabel]:
        self._ensure_load_started()
        return [_STAR_LABEL, _BOX_LABEL]

    def list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ) -> list[MapMaskPoint]:
        self._ensure_load_started()
        if map_name and map_name != _MAP_NAME:
            return []
        with self._lock:
            points = list(self._points)
        if label_ids is not None:
            selected = set(label_ids)
            points = [point for point in points if point.label_id in selected]
        return points

    def get_point_detail(self, point_id: str) -> dict[str, Any]:
        self._ensure_load_started()
        with self._lock:
            point = self._point_by_id.get(str(point_id))
        if point is None:
            raise ValueError(f"map mask point not found: {point_id}")
        return point.to_dict()

    def get_data_status(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state
            error = self._load_error
            point_count = len(self._points)
        return {
            "data_source": "pearpal-public",
            "labels_source": "pearpal-public",
            "points_source": f"pearpal-public-{state}",
            "labels_path": "",
            "points_path": "",
            "labels_error": "",
            "points_error": error,
            "point_count": point_count,
            "anonymous": True,
            "world_id": _WORLD_ID,
            "map_name": _MAP_NAME,
        }

    def _ensure_load_started(self) -> None:
        if not self.enabled:
            raise RuntimeError("OfficialPearPalProvider is disabled")
        with self._lock:
            if self._load_state != "idle":
                return
            self._load_state = "loading"
        if not self._background:
            self._load()
            return
        threading.Thread(
            target=self._load,
            name="map-mask-pearpal-load",
            daemon=True,
        ).start()

    def _load(self) -> None:
        try:
            points = self._fetch_points()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._load_state = "error"
                self._load_error = str(exc)
            logger.warning(f"failed to load anonymous PearPal map points: {exc}")
            return
        point_by_id = {point.id: point for point in points}
        with self._lock:
            self._points = tuple(point_by_id.values())
            self._point_by_id = point_by_id
            self._load_state = "ready"
            self._load_error = ""
        star_count = sum(point.label_id == _STAR_LABEL.id for point in points)
        box_count = sum(point.label_id == _BOX_LABEL.id for point in points)
        logger.info(
            "loaded anonymous PearPal map points: "
            f"star={star_count}, box={box_count}, total={len(point_by_id)}"
        )

    def _fetch_points(self) -> list[MapMaskPoint]:
        catalog_response, _ = self._client.fetch_catalog(_WORLD_ID)
        base_spawners, _ = self._client.fetch_spawners(_WORLD_ID)
        stage_spawners, _ = self._client.fetch_stage_spawners()
        spawners, _ = expand_stage_spawners(base_spawners, stage_spawners)

        catalogs = flatten_catalogs(catalog_response, self._language)
        catalog_by_id = {
            str(catalog.get("id")): catalog
            for catalog in catalogs
            if catalog.get("id") not in (None, "")
        }
        box_catalog_ids = {
            catalog_id
            for catalog_id, catalog in catalog_by_id.items()
            if str(catalog.get("_group_id") or "") == _BOX_CATALOG_GROUP_ID
        }

        points: list[MapMaskPoint] = []
        seen_source_ids: set[str] = set()
        for raw in spawners:
            source_id = str(raw.get("id") or "")
            catalog_id = str(spawner_catalog_id(raw) or "")
            if not source_id or source_id in seen_source_ids:
                continue
            if catalog_id in _STAR_CATALOG_IDS:
                label = _STAR_LABEL
            elif catalog_id in box_catalog_ids:
                label = _BOX_LABEL
            else:
                continue
            world_id = str(spawner_world_id(raw) or _WORLD_ID)
            if world_id != _WORLD_ID:
                continue
            web_x = _finite_float(raw.get("x"))
            web_y = _finite_float(raw.get("y"))
            if web_x is None or web_y is None:
                continue

            catalog = catalog_by_id.get(catalog_id, {})
            catalog_name = str(catalog.get("_localized_name") or "")
            description = localized_text(raw.get("description"), self._language)
            point_name = description or catalog_name or f"{label.name} {source_id}"
            stage_id = spawner_stage_id(raw)
            seen_source_ids.add(source_id)
            points.append(
                MapMaskPoint(
                    id=f"pearpal:{source_id}",
                    label_id=label.id,
                    name=point_name,
                    map_name=_MAP_NAME,
                    image_x=web_x * _MIRALAND_SCALE_X + _MIRALAND_OFFSET_X,
                    image_y=web_y * _MIRALAND_SCALE_Y + _MIRALAND_OFFSET_Y,
                    icon=str(catalog.get("_icon") or ""),
                    provider=self.name,
                    detail={
                        "source_id": source_id,
                        "world_id": world_id,
                        "catalog_id": catalog_id,
                        "catalog_name": catalog_name,
                        "catalog_group_id": str(catalog.get("_group_id") or ""),
                        "catalog_group_name": str(catalog.get("_group_name") or ""),
                        "description": description,
                        "web_x": web_x,
                        "web_y": web_y,
                        "web_z": _finite_float(raw.get("z")) or 0.0,
                        "stage_id": stage_id or "",
                        "parent_stage_id": str(raw.get("parentStageId") or ""),
                        "parent_id": str(raw.get("parentId") or ""),
                        "is_stage_expanded": bool(raw.get("is_stage_expanded")),
                        "awarded": False,
                        "anonymous": True,
                        "coordinate_transform": "pearpal-world-1-to-miraland-v12-standard",
                    },
                )
            )
        return points


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
