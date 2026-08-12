from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from whimbox.common.logger import logger

from .models import MapMaskLabel, MapMaskPoint
from .resource_paths import (
    development_map_mask_dir,
    package_map_mask_dir,
)


class LocalJsonProvider:
    name = "local"

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else _default_sample_data_dir()
        self._labels: list[MapMaskLabel] | None = None
        self._points: list[MapMaskPoint] | None = None
        self._data_status: dict[str, Any] = {
            "data_source": "pending",
            "labels_source": "pending",
            "points_source": "pending",
            "labels_path": "",
            "points_path": "",
            "labels_error": "",
            "points_error": "",
        }

    def list_labels(self) -> list[MapMaskLabel]:
        if self._labels is None:
            items, source, path, error = self._load_labels()
            self._labels = [MapMaskLabel.from_dict(item) for item in items]
            self._data_status.update(
                {
                    "labels_source": source,
                    "labels_path": str(path) if path else "",
                    "labels_error": error,
                }
            )
        self._ensure_points_loaded()
        self._register_unknown_point_labels()
        return list(self._labels)

    def list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ) -> list[MapMaskPoint]:
        self._ensure_points_loaded()
        if self._labels is not None:
            self._register_unknown_point_labels()
        assert self._points is not None
        points = list(self._points)
        if label_ids is not None:
            selected = set(label_ids)
            points = [point for point in points if point.label_id in selected]
        if map_name:
            points = [point for point in points if point.map_name == map_name]
        return points

    def _ensure_points_loaded(self) -> None:
        if self._points is not None:
            return
        items, source, path, error = self._load_points()
        self._points = [MapMaskPoint.from_dict(item) for item in items]
        self._data_status.update(
            {
                "data_source": _data_source_for_points(source),
                "points_source": source,
                "points_path": str(path) if path else "",
                "points_error": error,
            }
        )

    def _register_unknown_point_labels(self) -> None:
        if self._labels is None or self._points is None:
            return
        known_ids = {label.id for label in self._labels}
        generated_ids: list[str] = []
        provider_by_label: dict[str, str] = {}
        icon_by_label: dict[str, str] = {}
        for point in self._points:
            if not point.label_id or point.label_id in known_ids:
                continue
            provider_by_label.setdefault(point.label_id, point.provider or "local")
            icon_by_label.setdefault(point.label_id, point.icon or "marker.svg")
            self._labels.append(
                MapMaskLabel(
                    id=point.label_id,
                    name=point.label_id,
                    parent_id=None,
                    icon=icon_by_label[point.label_id],
                    provider=provider_by_label[point.label_id],
                    default_enabled=True,
                )
            )
            known_ids.add(point.label_id)
            generated_ids.append(point.label_id)
        if generated_ids:
            self._data_status["generated_label_ids"] = generated_ids
            logger.warning(
                "generated fallback map-mask labels for unknown point labels: "
                + ", ".join(generated_ids)
            )

    def get_point_detail(self, point_id: str) -> dict[str, Any]:
        for point in self.list_points():
            if point.id == point_id:
                return {
                    "id": point.id,
                    "label_id": point.label_id,
                    "name": point.name,
                    "map_name": point.map_name,
                    "icon": point.icon,
                    "provider": point.provider,
                    "detail": point.detail,
                }
        raise ValueError(f"map mask point not found: {point_id}")

    def get_data_status(self) -> dict[str, Any]:
        if self._labels is None:
            self.list_labels()
        if self._points is None:
            self.list_points()
        return dict(self._data_status)

    def _load_labels(self) -> tuple[list[dict[str, Any]], str, Path | None, str]:
        sample_path = self.data_dir / "labels.sample.json"
        sample_items, sample_error = _load_json_list_from_path(sample_path)
        if sample_error:
            logger.warning(f"failed to load map mask sample labels {sample_path}: {sample_error}")
            sample_items = _fallback_labels()

        local_path = _resolve_local_resource(
            env_name="WHIMBOX_MAP_MASK_LABELS",
            file_name="labels.local.json",
        )
        if local_path is None:
            return sample_items, "sample", sample_path, ""

        local_items, local_error = _load_json_list_from_path(local_path)
        if local_error:
            logger.warning(f"failed to load map mask local labels {local_path}: {local_error}")
            return sample_items, "fallback", sample_path, local_error
        if not local_items:
            return sample_items, "sample", sample_path, ""

        return _merge_labels(sample_items, local_items), "local", local_path, ""

    def _load_points(self) -> tuple[list[dict[str, Any]], str, Path | None, str]:
        sample_path = self.data_dir / "points.sample.json"
        sample_items, sample_error = _load_json_list_from_path(sample_path)
        if sample_error:
            logger.warning(f"failed to load map mask sample points {sample_path}: {sample_error}")
            sample_items = _fallback_points()

        local_path = _resolve_local_resource(
            env_name="WHIMBOX_MAP_MASK_LOCAL_POINTS",
            file_name="points.local.json",
        )
        if local_path is None:
            return sample_items, "sample", sample_path, ""

        local_items, local_error = _load_json_list_from_path(local_path)
        if local_error:
            logger.warning(f"failed to load map mask local points {local_path}: {local_error}")
            return sample_items, "fallback", sample_path, local_error
        if not local_items:
            return sample_items, "sample", sample_path, ""

        return local_items, "local", local_path, ""

    def _load_json_list(
        self,
        file_name: str,
        fallback: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                return data
            logger.warning(f"map mask local data is not a list: {path}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"failed to load map mask local data {path}: {exc}")
        return fallback


def _load_json_list_from_path(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)
        if not isinstance(data, list):
            return [], f"JSON root must be a list: {path}"
        items = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                return [], f"item {index} must be an object: {path}"
            items.append(item)
        return items, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def _merge_labels(
    sample_items: list[dict[str, Any]],
    local_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in [*sample_items, *local_items]:
        label_id = str(item.get("id") or "")
        if not label_id:
            continue
        if label_id not in merged:
            order.append(label_id)
        merged[label_id] = item
    return [merged[label_id] for label_id in order]


def _data_source_for_points(source: str) -> str:
    if source == "local":
        return "local"
    if source == "fallback":
        return "fallback"
    return "sample"


def _default_sample_data_dir() -> Path:
    return package_map_mask_dir()


def default_local_points_path() -> Path:
    configured = os.environ.get("WHIMBOX_MAP_MASK_LOCAL_POINTS")
    if configured:
        return _safe_resolve(Path(configured))
    return development_map_mask_dir() / "points.local.json"


def default_local_labels_path() -> Path:
    configured = os.environ.get("WHIMBOX_MAP_MASK_LABELS")
    if configured:
        return _safe_resolve(Path(configured))
    return development_map_mask_dir() / "labels.local.json"


def _resolve_local_resource(
    *,
    env_name: str,
    file_name: str,
) -> Path | None:
    configured = os.environ.get(env_name)
    if configured:
        return _safe_resolve(Path(configured))
    for directory in (package_map_mask_dir(), development_map_mask_dir()):
        candidate = directory / file_name
        if candidate.is_file():
            return candidate
    return None


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except Exception:
        return path


def _fallback_labels() -> list[dict[str, Any]]:
    return [
        {
            "id": "teleport",
            "name": "Teleport",
            "parent_id": None,
            "icon": "teleport.svg",
            "provider": "local",
            "default_enabled": True,
        },
        {
            "id": "material",
            "name": "Material",
            "parent_id": None,
            "icon": "material.svg",
            "provider": "local",
            "default_enabled": True,
        },
        {
            "id": "fish",
            "name": "Fish",
            "parent_id": None,
            "icon": "fish.svg",
            "provider": "local",
            "default_enabled": False,
        },
        {
            "id": "bug",
            "name": "Bug",
            "parent_id": None,
            "icon": "bug.svg",
            "provider": "local",
            "default_enabled": False,
        },
    ]


def _fallback_points() -> list[dict[str, Any]]:
    return [
        {
            "id": "point_001",
            "label_id": "material",
            "name": "Sample material A",
            "map_name": "miraland",
            "image_x": 1234.5,
            "image_y": 6789.0,
            "game_x": None,
            "game_y": None,
            "icon": "material.svg",
            "provider": "local",
            "detail": {"description": "Sample local point A.", "images": []},
        },
        {
            "id": "point_002",
            "label_id": "teleport",
            "name": "Sample teleport B",
            "map_name": "miraland",
            "image_x": 1500.0,
            "image_y": 7000.0,
            "game_x": None,
            "game_y": None,
            "icon": "teleport.svg",
            "provider": "local",
            "detail": {"description": "Sample local teleport B.", "images": []},
        },
    ]
