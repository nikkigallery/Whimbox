from __future__ import annotations

import math
import threading
import time
from dataclasses import replace
from typing import Any, Callable

from whimbox.common.logger import logger

from .pearpal_auth import (
    PearPalAwardedState,
    PearPalCredentials,
    PearPalLoginCancelled,
    PearPalUserClient,
    clear_webview_login_storage,
    launch_login_webview,
)
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
# PearPal groups each region's equivalent inspiration collectible under the
# dewdrop user-state field.
_DEWDROP_CATALOG_IDS = frozenset({"12", "133", "146", "168", "245"})
# Website source merges reading collectible IDs into the user info ``read`` list.
_READ_CATALOG_IDS = frozenset({"20"})
_USER_REFRESH_PERIOD_SECONDS = 30.0
_USER_REFRESH_MIN_INTERVAL_SECONDS = 5.0
_USER_REFRESH_BACKOFF_SECONDS = (5.0, 15.0, 30.0, 60.0)


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
_DEWDROP_LABEL = MapMaskLabel(
    id="pearpal_dewdrop",
    name="\u7075\u611f\u9732\u73e0",
    provider="pearpal",
    default_enabled=True,
)
_BOX_LABEL = MapMaskLabel(
    id="pearpal_box",
    name="宝箱",
    provider="pearpal",
    default_enabled=True,
)
_READ_LABEL = MapMaskLabel(
    id="pearpal_read",
    name="阅读物",
    provider="pearpal",
    default_enabled=True,
)
class OfficialPearPalProvider:
    """Anonymous PearPal public point provider.

    Loading starts lazily on the first overlay request. Production callers use
    a daemon thread so public API latency never blocks the 50 ms overlay poll.
    Authentication runs in an isolated Python WebView process; only the backend
    receives credentials and applies per-user awarded-state filtering.
    """

    name = "pearpal"

    def __init__(
        self,
        enabled: bool = False,
        *,
        client: Any | None = None,
        background: bool = True,
        language: str = "zh-cn",
        user_client: Any | None = None,
        login_launcher: Callable[[], PearPalCredentials] | None = None,
        login_background: bool = True,
        refresh_background: bool = True,
    ) -> None:
        self.enabled = enabled
        self._client = client or PearPalPublicDebugClient(language=language)
        self._background = background
        self._refresh_background = refresh_background
        self._language = language
        self._lock = threading.RLock()
        self._user_client = user_client or PearPalUserClient()
        self._login_launcher = login_launcher or launch_login_webview
        self._login_background = login_background
        self._load_state = "idle"
        self._load_error = ""
        self._points: tuple[MapMaskPoint, ...] = ()
        self._point_by_id: dict[str, MapMaskPoint] = {}
        self._source_ids_by_label: dict[str, frozenset[str]] = {}
        self._matched_awarded_counts = (0, 0, 0, 0)
        self._credentials: PearPalCredentials | None = None
        self._auth_generation = 0
        self._awarded_state = PearPalAwardedState(frozenset(), frozenset())
        self._auth_state = "anonymous"
        self._auth_error = ""
        self._hide_awarded = True
        self._login_thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None
        self._refreshing = False
        self._refresh_error = ""
        self._refresh_failure_count = 0
        self._refresh_reason = ""
        self._last_refresh_at = ""
        self._last_refresh_reason = ""
        self._last_refresh_monotonic = 0.0
        self._next_refresh_monotonic = 0.0
        self._overlay_bigmap_open = False

    def list_labels(self) -> list[MapMaskLabel]:
        return [
            _STAR_LABEL,
            _DEWDROP_LABEL,
            _BOX_LABEL,
            _READ_LABEL,
        ]

    def list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ) -> list[MapMaskPoint]:
        self._ensure_load_started()
        if map_name and map_name != _MAP_NAME:
            return []
        with self._lock:
            points = self._points
            hide_awarded = self._hide_awarded and self._credentials is not None
            awarded_state = self._awarded_state
        selected = set(label_ids) if label_ids is not None else None
        return [
            point
            for point in points
            if (selected is None or point.label_id in selected)
            and (
                not hide_awarded
                or not self._is_point_awarded(point, awarded_state)
            )
        ]

    def get_point_detail(self, point_id: str) -> dict[str, Any]:
        self._ensure_load_started()
        with self._lock:
            point = self._point_by_id.get(str(point_id))
            authenticated = self._credentials is not None
            awarded_state = self._awarded_state
        if point is None:
            raise ValueError(f"map mask point not found: {point_id}")
        return self._decorate_point(
            point,
            authenticated=authenticated,
            awarded_state=awarded_state,
        ).to_dict()

    def get_data_status(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state
            error = self._load_error
            point_count = len(self._points)
        user_status = self.get_user_status()
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
            **user_status,
        }

    def start_login(self) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("OfficialPearPalProvider is disabled")
        with self._lock:
            if self._login_thread is not None:
                return self.get_user_status()
            auth_generation = self._auth_generation
            self._auth_state = "opening-login"
            self._auth_error = ""
            if self._login_background:
                thread = threading.Thread(
                    target=self._login_and_refresh,
                    args=(auth_generation,),
                    name="map-mask-pearpal-login",
                    daemon=True,
                )
                self._login_thread = thread
            else:
                thread = None
        if thread is None:
            self._login_and_refresh(auth_generation)
        else:
            thread.start()
        return self.get_user_status()

    def disconnect_user(self) -> dict[str, Any]:
        with self._lock:
            self._auth_generation += 1
            self._reset_user_state_locked()
        return self.get_user_status()

    def clear_login_information(self) -> dict[str, Any]:
        with self._lock:
            self._auth_generation += 1
            self._reset_user_state_locked()
        clear_webview_login_storage()
        return self.get_user_status()

    def set_hide_awarded(self, hide_awarded: bool) -> dict[str, Any]:
        with self._lock:
            self._hide_awarded = bool(hide_awarded)
        return self.get_user_status()

    def refresh_user_state(self) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("OfficialPearPalProvider is disabled")
        self._schedule_user_refresh(reason="manual", force=True)
        return self.get_user_status()

    def note_overlay_activity(self, *, is_bigmap_open: bool) -> None:
        now = time.monotonic()
        with self._lock:
            was_bigmap_open = self._overlay_bigmap_open
            self._overlay_bigmap_open = bool(is_bigmap_open)
            if self._credentials is None:
                return
            map_opened = bool(is_bigmap_open) and not was_bigmap_open
            retry_due = (
                self._refresh_failure_count > 0
                and now >= self._next_refresh_monotonic
            )
            periodic_due = (
                self._last_refresh_monotonic <= 0.0
                or now - self._last_refresh_monotonic
                >= _USER_REFRESH_PERIOD_SECONDS
            )
        if map_opened:
            self._schedule_user_refresh(reason="map-open", force=False)
        elif retry_due:
            self._schedule_user_refresh(reason="retry", force=False)
        elif periodic_due:
            self._schedule_user_refresh(reason="periodic", force=False)

    def note_overlay_inactive(self) -> None:
        with self._lock:
            self._overlay_bigmap_open = False

    def _schedule_user_refresh(self, *, reason: str, force: bool) -> bool:
        with self._lock:
            credentials = self._credentials
            refresh_thread_running = bool(
                self._refresh_thread is not None
                and self._refresh_thread.is_alive()
            )
            if credentials is None or self._refreshing or refresh_thread_running:
                return False
            now = time.monotonic()
            if not force and now < self._next_refresh_monotonic:
                return False
            self._refreshing = True
            self._refresh_error = ""
            self._refresh_reason = reason
            auth_generation = self._auth_generation
            if self._refresh_background:
                thread = threading.Thread(
                    target=self._refresh_user_state,
                    args=(credentials, reason, auth_generation),
                    name="map-mask-pearpal-user-refresh",
                    daemon=True,
                )
                self._refresh_thread = thread
            else:
                thread = None
        if thread is None:
            self._refresh_user_state(credentials, reason, auth_generation)
        else:
            thread.start()
        return True

    def _refresh_user_state(
        self,
        credentials: PearPalCredentials,
        reason: str,
        auth_generation: int,
    ) -> None:
        try:
            awarded_state = self._user_client.fetch_awarded_state(credentials)
        except Exception as exc:  # noqa: BLE001
            should_log = False
            with self._lock:
                if (
                    self._auth_generation == auth_generation
                    and self._credentials == credentials
                ):
                    self._refreshing = False
                    self._refresh_error = str(exc)
                    self._refresh_reason = ""
                    self._refresh_failure_count += 1
                    backoff_index = min(
                        self._refresh_failure_count - 1,
                        len(_USER_REFRESH_BACKOFF_SECONDS) - 1,
                    )
                    self._next_refresh_monotonic = (
                        time.monotonic()
                        + _USER_REFRESH_BACKOFF_SECONDS[backoff_index]
                    )
                    should_log = True
            if should_log:
                logger.warning(
                    "failed to refresh PearPal user collection state: "
                    f"{type(exc).__name__}: {exc}"
                )
        else:
            refreshed = False
            with self._lock:
                if (
                    self._auth_generation == auth_generation
                    and self._credentials == credentials
                ):
                    now = time.monotonic()
                    self._set_awarded_state_locked(awarded_state)
                    self._refreshing = False
                    self._refresh_error = ""
                    self._refresh_failure_count = 0
                    self._refresh_reason = ""
                    self._last_refresh_at = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(),
                    )
                    self._last_refresh_reason = reason
                    self._last_refresh_monotonic = now
                    self._next_refresh_monotonic = (
                        now + _USER_REFRESH_MIN_INTERVAL_SECONDS
                    )
                    refreshed = True
            if refreshed:
                logger.info(
                    "refreshed PearPal user collection state: "
                    f"reason={reason}, star={len(awarded_state.star_ids)}, "
                    f"dewdrop={len(awarded_state.dewdrop_ids)}, "
                    f"box={len(awarded_state.box_ids)}, "
                    f"read={len(awarded_state.read_ids)}"
                )
        finally:
            with self._lock:
                if self._refresh_thread is threading.current_thread():
                    self._refresh_thread = None


    def get_user_status(self) -> dict[str, Any]:
        with self._lock:
            credentials = self._credentials
            awarded = self._awarded_state
            (
                matched_star,
                matched_dewdrop,
                matched_box,
                matched_read,
            ) = self._matched_awarded_counts
            next_refresh_in_seconds = 0.0
            if credentials is not None and self._next_refresh_monotonic > 0.0:
                next_refresh_in_seconds = max(
                    0.0,
                    self._next_refresh_monotonic - time.monotonic(),
                )
            return {
                "auth_state": self._auth_state,
                "authenticated": credentials is not None,
                "anonymous": credentials is None,
                "auth_error": self._auth_error,
                "openid_masked": credentials.masked_openid if credentials else "",
                "hide_awarded": self._hide_awarded,
                "refreshing": self._refreshing,
                "refresh_error": self._refresh_error,
                "refresh_failure_count": self._refresh_failure_count,
                "refresh_reason": self._refresh_reason,
                "last_refresh_at": self._last_refresh_at,
                "last_refresh_reason": self._last_refresh_reason,
                "next_refresh_in_seconds": round(next_refresh_in_seconds, 1),
                "awarded_star_count": len(awarded.star_ids),
                "awarded_dewdrop_count": len(awarded.dewdrop_ids),
                "awarded_box_count": len(awarded.box_ids),
                "awarded_read_count": len(awarded.read_ids),
                "matched_awarded_star_count": matched_star,
                "matched_awarded_dewdrop_count": matched_dewdrop,
                "matched_awarded_box_count": matched_box,
                "matched_awarded_read_count": matched_read,
            }

    def _login_and_refresh(self, auth_generation: int) -> None:
        try:
            credentials = self._login_launcher()
            with self._lock:
                if self._auth_generation != auth_generation:
                    return
                self._auth_state = "loading-user-state"
            awarded_state = self._user_client.fetch_awarded_state(credentials)
        except PearPalLoginCancelled:
            with self._lock:
                if self._auth_generation == auth_generation:
                    self._auth_state = "cancelled"
                    self._auth_error = ""
            return
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                is_current_login = self._auth_generation == auth_generation
                if is_current_login:
                    self._auth_state = "error"
                    self._auth_error = str(exc)
            if is_current_login:
                logger.warning(
                    "failed to load PearPal user collection state: "
                    f"{type(exc).__name__}: {exc}"
                )
            return
        finally:
            with self._lock:
                if self._login_thread is threading.current_thread():
                    self._login_thread = None
        now = time.monotonic()
        with self._lock:
            if self._auth_generation != auth_generation:
                return
            self._credentials = credentials
            self._set_awarded_state_locked(awarded_state)
            self._auth_state = "authenticated"
            self._auth_error = ""
            self._refreshing = False
            self._refresh_error = ""
            self._refresh_failure_count = 0
            self._refresh_reason = ""
            self._last_refresh_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            )
            self._last_refresh_reason = "login"
            self._last_refresh_monotonic = now
            self._next_refresh_monotonic = (
                now + _USER_REFRESH_MIN_INTERVAL_SECONDS
            )
        logger.info(
            "loaded PearPal user collection state: "
            f"star={len(awarded_state.star_ids)}, "
            f"dewdrop={len(awarded_state.dewdrop_ids)}, "
            f"box={len(awarded_state.box_ids)}, "
            f"read={len(awarded_state.read_ids)}"
        )

    def _reset_user_state_locked(self) -> None:
        self._credentials = None
        self._set_awarded_state_locked(
            PearPalAwardedState(frozenset(), frozenset())
        )
        self._auth_state = "anonymous"
        self._auth_error = ""
        self._refreshing = False
        self._refresh_error = ""
        self._refresh_failure_count = 0
        self._refresh_reason = ""
        self._last_refresh_at = ""
        self._last_refresh_reason = ""
        self._last_refresh_monotonic = 0.0
        self._next_refresh_monotonic = 0.0
        self._overlay_bigmap_open = False

    @staticmethod
    def _is_point_awarded(
        point: MapMaskPoint,
        awarded_state: PearPalAwardedState,
    ) -> bool:
        source_id = str(point.detail.get("source_id") or "")
        if point.label_id == _STAR_LABEL.id:
            return source_id in awarded_state.star_ids
        if point.label_id == _BOX_LABEL.id:
            return source_id in awarded_state.box_ids
        if point.label_id == _DEWDROP_LABEL.id:
            return source_id in awarded_state.dewdrop_ids
        if point.label_id == _READ_LABEL.id:
            return source_id in awarded_state.read_ids
        return False

    def _decorate_point(
        self,
        point: MapMaskPoint,
        *,
        authenticated: bool,
        awarded_state: PearPalAwardedState,
    ) -> MapMaskPoint:
        awarded = authenticated and self._is_point_awarded(point, awarded_state)
        detail = {
            **point.detail,
            "awarded": awarded,
            "anonymous": not authenticated,
        }
        return replace(point, detail=detail)

    def _set_awarded_state_locked(self, awarded_state: PearPalAwardedState) -> None:
        self._awarded_state = awarded_state
        self._matched_awarded_counts = (
            len(
                self._source_ids_by_label.get(_STAR_LABEL.id, frozenset())
                & awarded_state.star_ids
            ),
            len(
                self._source_ids_by_label.get(_DEWDROP_LABEL.id, frozenset())
                & awarded_state.dewdrop_ids
            ),
            len(
                self._source_ids_by_label.get(_BOX_LABEL.id, frozenset())
                & awarded_state.box_ids
            ),
            len(
                self._source_ids_by_label.get(_READ_LABEL.id, frozenset())
                & awarded_state.read_ids
            ),
        )

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
        source_ids_by_label: dict[str, set[str]] = {
            _STAR_LABEL.id: set(),
            _DEWDROP_LABEL.id: set(),
            _BOX_LABEL.id: set(),
            _READ_LABEL.id: set(),
        }
        for point in point_by_id.values():
            source_id = str(point.detail.get("source_id") or "")
            if source_id and point.label_id in source_ids_by_label:
                source_ids_by_label[point.label_id].add(source_id)
        with self._lock:
            self._points = tuple(point_by_id.values())
            self._point_by_id = point_by_id
            self._source_ids_by_label = {
                label_id: frozenset(source_ids)
                for label_id, source_ids in source_ids_by_label.items()
            }
            self._set_awarded_state_locked(self._awarded_state)
            self._load_state = "ready"
            self._load_error = ""
        star_count = sum(point.label_id == _STAR_LABEL.id for point in points)
        dewdrop_count = sum(point.label_id == _DEWDROP_LABEL.id for point in points)
        box_count = sum(point.label_id == _BOX_LABEL.id for point in points)
        read_count = sum(point.label_id == _READ_LABEL.id for point in points)
        logger.info(
            "loaded anonymous PearPal map points: "
            f"star={star_count}, dewdrop={dewdrop_count}, box={box_count}, "
            f"read={read_count}, "
            f"total={len(point_by_id)}"
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
            elif catalog_id in _DEWDROP_CATALOG_IDS:
                label = _DEWDROP_LABEL
            elif catalog_id in box_catalog_ids:
                label = _BOX_LABEL
            elif catalog_id in _READ_CATALOG_IDS:
                label = _READ_LABEL
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
