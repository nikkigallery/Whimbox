from __future__ import annotations

from typing import Protocol

from .models import MapMaskLabel, MapMaskPoint


class MapMaskProvider(Protocol):
    name: str

    def list_labels(self) -> list[MapMaskLabel]:
        ...

    def list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ) -> list[MapMaskPoint]:
        ...

    def get_point_detail(self, point_id: str) -> dict:
        ...
