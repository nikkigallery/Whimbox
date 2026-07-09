from __future__ import annotations

from .models import MapMaskLabel, MapMaskPoint


class OfficialPearPalProvider:
    """Placeholder for safe public PearPal resources.

    The sample MVP intentionally does not call official services. This class
    keeps the provider boundary ready while LocalJsonProvider remains the
    default fallback.
    """

    name = "pearpal"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def list_labels(self) -> list[MapMaskLabel]:
        self._raise_unavailable()

    def list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ) -> list[MapMaskPoint]:
        self._raise_unavailable()

    def get_point_detail(self, point_id: str) -> dict:
        self._raise_unavailable()

    def _raise_unavailable(self) -> None:
        raise RuntimeError(
            "OfficialPearPalProvider is disabled until safe public endpoints "
            "are discovered and documented."
        )
