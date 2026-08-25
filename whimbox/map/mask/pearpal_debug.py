from __future__ import annotations

import io
import hashlib
import json
import math
import os
import re
import statistics
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .pearpal_regions import REGIONS


USER_AGENT = "Whimbox-PearPal-Public-Debug/1.0"
MAX_JSON_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_SNAPPY_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_SNAPPY_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_TILE_BYTES = 5 * 1024 * 1024
WHIMBOX_PNG_TARGET = "whimbox_full_resolution_png"

# Known public-map naming differences. Unicode escapes keep this source ASCII-only.
DEFAULT_NAME_ALIASES = {
    "\u53e4\u6728\u840c\u5730\u9644\u8fd1\u9057\u8ff9":
        "\u53e4\u6728\u836b\u5730\u9644\u8fd1\u9057\u8ff9",
    "\u63a2\u9669\u5bb6\u5927\u8425\u5730":
        "\u63a2\u9669\u5927\u8425\u5730",
    "\u76d0\u6676\u644a":
        "\u76d0\u6676\u6ee9",
    "\u9f99\u5de2\u5c71\u98de\u7011\u5ea7\u9876":
        "\u9f99\u5de2\u5c71\u98de\u7011\u5d16\u9876",
}

PUBLIC_API_PATHS = {
    "/v1/strategy/map/world/config/list",
    "/v1/strategy/map/catalog/list",
    "/v1/strategy/map/spawner/list",
    "/v1/strategy/map/stage/spawner/list",
    "/v1/strategy/map/spawner/info",
}
FORBIDDEN_RESPONSE_KEYS = {
    "authorization",
    "cookie",
    "favorite",
    "favorites",
    "marked",
    "notes",
    "openid",
    "progress",
    "role_id",
    "token",
    "uid",
    "user_id",
    "user_info",
}
PUBLIC_SPAWNER_FIELDS = {
    "id",
    "name",
    "x",
    "y",
    "z",
    "catalog",
    "catalog_id",
    "catalogId",
    "category",
    "catalog_ids",
    "world_id",
    "worldId",
    "stage_id",
    "stageId",
    "description",
    "tag",
    "tags",
    "layer_id",
    "layered_map_id",
    "layeredMapId",
    "type",
    "visible",
    "parent_id",
    "parent_stage_id",
    "parentCatalogId",
    "parentId",
    "parentStageId",
    "is_stage_expanded",
}
PUBLIC_STAGE_SPAWNER_FIELDS = {
    "id",
    "catalog",
    "description",
    "tag",
}


class PearPalDebugError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchResult:
    body: bytes
    cache_hit: bool
    cache_path: Path | None


class PearPalPublicDebugClient:
    """Anonymous, allowlisted client used only by the PearPal debug CLI."""

    def __init__(
        self,
        *,
        region: str = "cn",
        language: str = "zh-cn",
        client_id: str | None = None,
        no_cache: bool = False,
        refresh: bool = False,
        cache_dir: str | Path | None = None,
        request_interval_seconds: float = 0.5,
    ) -> None:
        try:
            self.region = REGIONS[region]
        except KeyError as exc:
            raise PearPalDebugError(f"unsupported PearPal region: {region}") from exc
        self.language = _safe_component(language)
        self.no_cache = no_cache
        self.refresh = refresh
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self._last_request_at = 0.0
        self._client_id = _validate_client_id(client_id) if client_id else None
        self._allowed_hosts = {
            urllib.parse.urlsplit(item).hostname
            for item in (
                self.region.page_url,
                self.region.api_base,
                self.region.asset_base,
            )
        }

    @property
    def client_id(self) -> str:
        if self._client_id is None:
            self._client_id = self._discover_public_client_id()
        return self._client_id

    def fetch_world_config(self) -> tuple[dict[str, Any], FetchResult]:
        result = self._post_cached(
            "/v1/strategy/map/world/config/list",
            {},
            f"world-config-{self.region.name}-{self.language}.json",
            MAX_JSON_RESPONSE_BYTES,
        )
        return _decode_api_json(result.body, "world config"), result

    def fetch_catalog(self, world_id: str) -> tuple[dict[str, Any], FetchResult]:
        world = _validate_identifier(world_id, "world id")
        result = self._post_cached(
            "/v1/strategy/map/catalog/list",
            {"world_id": world},
            f"catalog-{self.region.name}-world-{_safe_component(world)}-{self.language}.json",
            MAX_JSON_RESPONSE_BYTES,
        )
        return _decode_api_json(result.body, "catalog"), result

    def fetch_spawners(
        self,
        world_id: str,
    ) -> tuple[list[dict[str, Any]], FetchResult]:
        world = _validate_identifier(world_id, "world id")
        result = self._post_cached(
            "/v1/strategy/map/spawner/list",
            # The public bundle names this catalog_type_id, but it is a catalog
            # group selector and rewrites the returned catalog field. An empty
            # selector preserves the real per-spawner catalog IDs.
            {"world_id": world, "catalog_type_id": []},
            (
                f"spawner-{self.region.name}-world-{_safe_component(world)}"
                f"-catalog-all-{self.language}.snappy"
            ),
            MAX_SNAPPY_RESPONSE_BYTES,
        )
        payload = decode_snappy_json(result.body)
        _reject_private_fields(payload)
        points = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(points, list):
            raise PearPalDebugError("spawner response schema changed: expected a list field")
        sanitized: list[dict[str, Any]] = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                raise PearPalDebugError(f"spawner response item {index} is not an object")
            sanitized.append(sanitize_public_spawner(point))
        return sanitized, result

    def fetch_stage_spawners(
        self,
    ) -> tuple[dict[str, list[dict[str, Any]]], FetchResult]:
        result = self._post_cached(
            "/v1/strategy/map/stage/spawner/list",
            {},
            (
                f"stage-spawner-{self.region.name}-world-all"
                f"-catalog-all-{self.language}.snappy"
            ),
            MAX_SNAPPY_RESPONSE_BYTES,
        )
        payload = decode_snappy_json(result.body)
        _reject_private_fields(payload)
        stages = payload.get("stages") if isinstance(payload, dict) else None
        if not isinstance(stages, dict):
            raise PearPalDebugError(
                "stage spawner response schema changed: expected a stages object"
            )
        sanitized: dict[str, list[dict[str, Any]]] = {}
        for stage_id, points in stages.items():
            if not isinstance(points, list):
                raise PearPalDebugError(
                    f"stage spawner entry {stage_id} is not a list"
                )
            sanitized_points: list[dict[str, Any]] = []
            for index, point in enumerate(points):
                if not isinstance(point, dict):
                    raise PearPalDebugError(
                        f"stage {stage_id} item {index} is not an object"
                    )
                unknown_fields = set(point) - PUBLIC_STAGE_SPAWNER_FIELDS
                if unknown_fields:
                    raise PearPalDebugError(
                        "stage spawner response schema changed; refusing unknown fields: "
                        + ", ".join(sorted(unknown_fields))
                    )
                sanitized_points.append(
                    {
                        key: point[key]
                        for key in PUBLIC_STAGE_SPAWNER_FIELDS
                        if key in point
                    }
                )
            sanitized[str(stage_id)] = sanitized_points
        return sanitized, result

    def validate_single_tile(
        self,
        *,
        map_resource_url: str,
        zoom: int,
        tile_x: int,
        tile_y: int,
    ) -> dict[str, Any]:
        resource = _validate_resource_name(map_resource_url)
        url = (
            f"{self.region.asset_base}/maps/{resource}/{zoom}-{tile_x}-{tile_y}.webp"
            "?x-oss-process=image/format,webp"
        )
        body, headers = self._request("GET", url, None, MAX_TILE_BYTES)
        width, height, image_format = _inspect_image(body)
        return {
            "url": url,
            "status": "ok",
            "content_type": headers.get("Content-Type", ""),
            "bytes": len(body),
            "width": width,
            "height": height,
            "format": image_format,
            "is_256_tile": width == 256 and height == 256,
        }

    def _post_cached(
        self,
        api_path: str,
        payload: dict[str, Any],
        cache_name: str,
        max_bytes: int,
    ) -> FetchResult:
        if api_path not in PUBLIC_API_PATHS:
            raise PearPalDebugError(f"endpoint is not in the public debug allowlist: {api_path}")
        _reject_forbidden_request_fields(payload)
        cache_path = self.cache_dir / cache_name
        if not self.no_cache and not self.refresh and cache_path.is_file():
            return FetchResult(cache_path.read_bytes(), True, cache_path)

        request_payload = {"client_id": int(self.client_id), **payload}
        body = json.dumps(request_payload, separators=(",", ":")).encode("utf-8")
        response, _headers = self._request(
            "POST",
            f"{self.region.api_base}{api_path}",
            body,
            max_bytes,
            content_type="application/json",
        )
        if not self.no_cache:
            _write_bytes_atomic(cache_path, response)
            return FetchResult(response, False, cache_path)
        return FetchResult(response, False, None)

    def _discover_public_client_id(self) -> str:
        cache_path = self.cache_dir / f"public-client-id-{self.region.name}.json"
        if not self.no_cache and not self.refresh and cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                return _validate_client_id(str(cached["client_id"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

        html_bytes, _headers = self._request(
            "GET",
            self.region.page_url,
            None,
            MAX_BUNDLE_BYTES,
        )
        html = html_bytes.decode("utf-8", errors="replace")
        script_sources = re.findall(
            r"<script[^>]+src=[\"']([^\"']+)[\"']",
            html,
            flags=re.IGNORECASE,
        )
        custom_urls = [
            urllib.parse.urljoin(self.region.page_url, source)
            for source in script_sources
            if "/js/custom." in source
        ]
        if not custom_urls:
            raise PearPalDebugError(
                "could not locate the public custom bundle; pass the public client id with --client-id"
            )

        pattern = re.compile(
            rf"{re.escape(self.region.client_name)}:\{{clientid:[\"'](\d+)[\"']"
        )
        for bundle_url in custom_urls[:1]:
            bundle_bytes, _headers = self._request(
                "GET",
                bundle_url,
                None,
                MAX_BUNDLE_BYTES,
            )
            match = pattern.search(bundle_bytes.decode("utf-8", errors="replace"))
            if not match:
                continue
            client_id = _validate_client_id(match.group(1))
            if not self.no_cache:
                _write_json_atomic(
                    cache_path,
                    {
                        "client_id": client_id,
                        "region": self.region.name,
                        "source_bundle": bundle_url,
                        "public_debug_only": True,
                    },
                )
            return client_id

        raise PearPalDebugError(
            "public client id extraction failed; pass the current public id with --client-id"
        )

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        max_bytes: int,
        *,
        content_type: str | None = None,
    ) -> tuple[bytes, Any]:
        self._validate_url(url)
        wait = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        headers = {
            "Accept": "application/json,image/webp,*/*;q=0.1",
            "User-Agent": USER_AGENT,
        }
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                self._last_request_at = time.monotonic()
                final_url = response.geturl()
                self._validate_url(final_url)
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise PearPalDebugError(
                        f"public response exceeds the {max_bytes}-byte safety limit"
                    )
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise PearPalDebugError(
                        f"public response exceeds the {max_bytes}-byte safety limit"
                    )
                return data, response.headers
        except PearPalDebugError:
            raise
        except Exception as exc:
            raise PearPalDebugError(
                f"anonymous public request failed for {url}: {type(exc).__name__}: {exc}. "
                "Keep using LocalJsonProvider."
            ) from exc

    def _validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in self._allowed_hosts:
            raise PearPalDebugError(f"refusing non-allowlisted URL: {url}")
        if parsed.username or parsed.password:
            raise PearPalDebugError("refusing URL with embedded credentials")


def default_cache_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Whimbox" / "map_mask" / "cache" / "pearpal"


def decode_snappy_json(data: bytes) -> dict[str, Any]:
    stripped = data.lstrip()
    if stripped.startswith((b"{", b"[")):
        payload = _decode_json_bytes(stripped, "spawner")
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise PearPalDebugError(
                f"PearPal public endpoint rejected the request: "
                f"code={payload.get('code')} info={payload.get('info')}"
            )
        if not isinstance(payload, dict):
            raise PearPalDebugError("spawner JSON response is not an object")
        return payload
    decompressed = snappy_decompress(data)
    payload = _decode_json_bytes(decompressed, "decompressed spawner")
    if not isinstance(payload, dict):
        raise PearPalDebugError("decompressed spawner response is not an object")
    return payload


def snappy_decompress(data: bytes) -> bytes:
    if not data:
        raise PearPalDebugError("empty Snappy response")
    index = 0
    expected_length, index = _read_varint(data, index)
    if expected_length > MAX_SNAPPY_OUTPUT_BYTES:
        raise PearPalDebugError(
            f"Snappy output length {expected_length} exceeds the safety limit"
        )
    output = bytearray()
    while index < len(data):
        tag = data[index]
        index += 1
        tag_type = tag & 0x03
        if tag_type == 0:
            literal_length = tag >> 2
            if literal_length < 60:
                literal_length += 1
            else:
                length_bytes = literal_length - 59
                if index + length_bytes > len(data):
                    raise PearPalDebugError("truncated Snappy literal length")
                literal_length = (
                    int.from_bytes(data[index : index + length_bytes], "little") + 1
                )
                index += length_bytes
            end = index + literal_length
            if end > len(data):
                raise PearPalDebugError("truncated Snappy literal")
            output.extend(data[index:end])
            index = end
        elif tag_type == 1:
            if index >= len(data):
                raise PearPalDebugError("truncated Snappy copy-1")
            copy_length = 4 + ((tag >> 2) & 0x07)
            offset = ((tag & 0xE0) << 3) | data[index]
            index += 1
            _copy_snappy(output, offset, copy_length)
        elif tag_type == 2:
            if index + 2 > len(data):
                raise PearPalDebugError("truncated Snappy copy-2")
            copy_length = 1 + (tag >> 2)
            offset = int.from_bytes(data[index : index + 2], "little")
            index += 2
            _copy_snappy(output, offset, copy_length)
        else:
            if index + 4 > len(data):
                raise PearPalDebugError("truncated Snappy copy-4")
            copy_length = 1 + (tag >> 2)
            offset = int.from_bytes(data[index : index + 4], "little")
            index += 4
            _copy_snappy(output, offset, copy_length)
        if len(output) > expected_length:
            raise PearPalDebugError("Snappy output exceeded its declared length")
    if len(output) != expected_length:
        raise PearPalDebugError(
            f"Snappy length mismatch: expected {expected_length}, got {len(output)}"
        )
    return bytes(output)


def sanitize_public_spawner(raw: dict[str, Any]) -> dict[str, Any]:
    _reject_private_fields(raw)
    unknown_fields = set(raw) - PUBLIC_SPAWNER_FIELDS
    if unknown_fields:
        raise PearPalDebugError(
            "spawner response schema changed; refusing unknown fields: "
            + ", ".join(sorted(unknown_fields))
        )
    return {key: raw[key] for key in PUBLIC_SPAWNER_FIELDS if key in raw}


def normalize_spawner(
    raw: dict[str, Any],
    *,
    requested_world_id: str,
    requested_catalog_id: str,
    catalog: dict[str, Any] | None,
    language: str,
    catalog_filter_resolved: bool = True,
) -> dict[str, Any]:
    sanitized = sanitize_public_spawner(raw)
    warnings: list[str] = []
    source_id = str(sanitized.get("id") or "")
    world_id = str(spawner_world_id(sanitized) or requested_world_id)
    catalog_id = str(spawner_catalog_id(sanitized) or "")
    web_x = _optional_finite_float(sanitized.get("x"))
    web_y = _optional_finite_float(sanitized.get("y"))
    z = _optional_finite_float(sanitized.get("z"))
    stage_id = spawner_stage_id(sanitized)
    if stage_id in ("", 0, "0"):
        stage_id = None
    if not source_id:
        warnings.append("missing source id")
    if web_x is None or web_y is None:
        warnings.append("missing or non-finite web coordinates")
    if world_id != str(requested_world_id):
        warnings.append("world id differs from requested world")
    if catalog_id != str(requested_catalog_id):
        warnings.append("catalog id differs from requested catalog")
    if not catalog_filter_resolved:
        warnings.append("catalog_filter_unresolved")
    if stage_id is not None:
        warnings.append("stage id present; web visibility needs stage/layer validation")

    description = localized_text(sanitized.get("description"), language)
    catalog_name = localized_text((catalog or {}).get("name"), language)
    name = description or (
        f"{catalog_name} {source_id}".strip() if catalog_name else f"PearPal point {source_id}"
    )
    tags = _normalize_tags(sanitized.get("tag"))
    is_stage_expanded = bool(
        sanitized.get("is_stage_expanded")
        or sanitized.get("parent_stage_id")
        or sanitized.get("parentStageId")
    )
    is_candidate_visible = (
        bool(source_id)
        and web_x is not None
        and web_y is not None
        and catalog_filter_resolved
        and world_id == str(requested_world_id)
        and catalog_id == str(requested_catalog_id)
    )
    return {
        "source_id": source_id,
        "catalog_id": catalog_id,
        "world_id": world_id,
        "name": name,
        "web_x": web_x,
        "web_y": web_y,
        "z": z if z is not None else 0.0,
        "stage_id": stage_id,
        "description": description,
        "icon": catalog_icon(catalog or {}),
        "raw_tags": tags,
        "is_stage_expanded": is_stage_expanded,
        "is_candidate_visible": is_candidate_visible,
        "normalization_warning": "; ".join(warnings),
        "raw": sanitized,
    }


def inspect_raw_spawner(
    raw: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    sanitized = sanitize_public_spawner(raw)
    return {
        "id": sanitized.get("id"),
        "name": raw_spawner_name(sanitized, language),
        "x": sanitized.get("x"),
        "y": sanitized.get("y"),
        "z": sanitized.get("z"),
        "world_id": sanitized.get("world_id"),
        "worldId": sanitized.get("worldId"),
        "resolved_world_id": spawner_world_id(sanitized),
        "catalog_id": sanitized.get("catalog_id"),
        "catalogId": sanitized.get("catalogId"),
        "catalog": sanitized.get("catalog"),
        "category": sanitized.get("category"),
        "catalog_ids": sanitized.get("catalog_ids"),
        "resolved_catalog_id": spawner_catalog_id(sanitized),
        "stage_id": sanitized.get("stage_id"),
        "stageId": sanitized.get("stageId"),
        "resolved_stage_id": spawner_stage_id(sanitized),
        "tag": sanitized.get("tag"),
        "tags": sanitized.get("tags"),
        "layer_id": sanitized.get("layer_id"),
        "layered_map_id": sanitized.get("layered_map_id"),
        "layeredMapId": sanitized.get("layeredMapId"),
        "type": sanitized.get("type"),
        "visible": sanitized.get("visible"),
        "raw_keys": sorted(sanitized),
    }


def raw_spawner_name(raw: dict[str, Any], language: str) -> str:
    return localized_text(raw.get("name") or raw.get("description"), language)


def spawner_world_id(raw: dict[str, Any]) -> str | None:
    return _first_identifier(raw, ("world_id", "worldId"))


def spawner_catalog_id(raw: dict[str, Any]) -> str | None:
    value = _first_identifier(
        raw,
        ("catalog_id", "catalogId", "catalog", "category"),
    )
    if value:
        return value
    catalog_ids = raw.get("catalog_ids")
    if isinstance(catalog_ids, list) and len(catalog_ids) == 1:
        return str(catalog_ids[0])
    return None


def spawner_stage_id(raw: dict[str, Any]) -> str | None:
    value = _first_identifier(raw, ("stage_id", "stageId"))
    return None if value in (None, "", "0") else value


def expand_stage_spawners(
    base_spawners: list[dict[str, Any]],
    stages: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expanded = list(base_spawners)
    parent_by_stage: dict[str, dict[str, Any]] = {}
    for spawner in base_spawners:
        stage_id = spawner_stage_id(spawner)
        if stage_id and stage_id not in parent_by_stage:
            parent_by_stage[stage_id] = spawner

    matched_stage_count = 0
    expanded_child_count = 0
    for stage_id, children in stages.items():
        parent = parent_by_stage.get(str(stage_id))
        if parent is None:
            continue
        matched_stage_count += 1
        for child in children:
            child_catalog = child.get("catalog")
            child_id = child.get("id")
            if child_catalog in (None, "") or child_id in (None, ""):
                continue
            clone = dict(parent)
            clone.update(
                {
                    "stage_id": "",
                    "id": child_id,
                    "catalog": child_catalog,
                    "parentCatalogId": spawner_catalog_id(parent),
                    "parentStageId": str(stage_id),
                    "parentId": parent.get("id"),
                    "description": child.get("description") or "",
                    "is_stage_expanded": True,
                }
            )
            expanded.append(sanitize_public_spawner(clone))
            expanded_child_count += 1
    return expanded, {
        "stage_relation_status": "resolved_official_bundle_expansion",
        "stage_count": len(stages),
        "matched_stage_parent_count": matched_stage_count,
        "expanded_stage_child_count": expanded_child_count,
        "reason": (
            "stage/spawner/list contains child id/catalog/description/tag records "
            "without coordinates; the public bundle clones the matching base "
            "stage parent's coordinates before catalog filtering"
        ),
    }


def flatten_catalogs(
    response: dict[str, Any],
    language: str,
) -> list[dict[str, Any]]:
    groups = extract_api_list(response, "catalog")
    flattened: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(
            group.get("id")
            or group.get("catalog_type_id")
            or group.get("type_id")
            or ""
        )
        group_name = localized_text(group.get("name"), language)
        catalogs = group.get("catalogs")
        if not isinstance(catalogs, list):
            continue
        for item in catalogs:
            if not isinstance(item, dict):
                continue
            flattened.append(
                {
                    **item,
                    "_group_id": group_id,
                    "_group_name": group_name,
                    "_localized_name": localized_text(item.get("name"), language),
                    "_icon": catalog_icon(item),
                }
            )
    return flattened


def find_catalog(
    response: dict[str, Any],
    catalog_id: str,
    language: str,
) -> dict[str, Any] | None:
    target = str(catalog_id)
    for catalog in flatten_catalogs(response, language):
        if str(catalog.get("id") or "") == target:
            return catalog
    return None


def extract_api_list(response: dict[str, Any], label: str) -> list[Any]:
    data = response.get("data")
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise PearPalDebugError(f"{label} response schema changed: expected data.list")
    return items


def localized_text(value: Any, language: str) -> str:
    parsed = value
    for _ in range(3):
        if not isinstance(parsed, str):
            break
        text = parsed.strip()
        if not text:
            return ""
        if not text.startswith(("[", "{", '"')):
            return text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        for key in _language_keys(language):
            if key in parsed:
                return localized_text(parsed[key], language)
        if "text" in parsed:
            return localized_text(parsed["text"], language)
        return ""
    if isinstance(parsed, list):
        entries = [item for item in parsed if isinstance(item, dict)]
        for key in _language_keys(language):
            for item in entries:
                if str(item.get("lang") or "").lower() == key:
                    return str(item.get("text") or "")
        for item in entries:
            if item.get("text"):
                return str(item["text"])
    return ""


def catalog_icon(catalog: dict[str, Any]) -> str:
    icon = catalog.get("icon")
    if isinstance(icon, str):
        return icon
    icons = catalog.get("icons")
    if isinstance(icons, list):
        for item in icons:
            if isinstance(item, dict) and isinstance(item.get("icon"), str):
                return item["icon"]
    return ""


def fit_pearpal_transform(
    landmarks: list[dict[str, Any]],
    *,
    flip_y_origin: float,
    flip_x_origin: float | None = None,
    fit_mode: str = "auto",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(landmarks) < 2:
        raise PearPalDebugError("at least two landmarks are required; 4-8 are recommended")
    if fit_mode not in {"axis-aligned", "affine", "auto"}:
        raise PearPalDebugError(f"unsupported transform fit mode: {fit_mode}")
    normalized = [_normalize_landmark(item, index) for index, item in enumerate(landmarks)]
    flip_x_origin = float(
        flip_x_origin
        if flip_x_origin is not None
        else (metadata or {}).get("flip_x_origin", (metadata or {}).get("web_map_size", 0.0))
    )
    flip_y_origin = float(flip_y_origin)
    if not math.isfinite(flip_x_origin) or not math.isfinite(flip_y_origin):
        raise PearPalDebugError("flip origins must be finite")

    requested_modes = (
        ("axis-aligned", "affine")
        if fit_mode == "auto"
        else (fit_mode,)
    )
    candidates: list[dict[str, Any]] = []
    candidate_errors: list[dict[str, str]] = []
    for mode in requested_modes:
        if mode == "affine" and len(normalized) < 3:
            candidate_errors.append(
                {
                    "fit_mode": mode,
                    "orientation": "all",
                    "error": "affine requires at least three landmarks",
                }
            )
            continue
        for orientation in _transform_orientations():
            try:
                candidate = _fit_transform_candidate(
                    normalized,
                    fit_mode=mode,
                    orientation=orientation,
                    flip_x_origin=flip_x_origin,
                    flip_y_origin=flip_y_origin,
                )
                loo = _leave_one_out(
                    normalized,
                    fit_mode=mode,
                    orientation=orientation,
                    flip_x_origin=flip_x_origin,
                    flip_y_origin=flip_y_origin,
                )
                candidate["loo_rmse"] = loo["rmse"]
                candidate["loo_available_count"] = loo["available_count"]
                candidate["selection_score"] = _candidate_selection_score(candidate)
                candidates.append(candidate)
            except PearPalDebugError as exc:
                candidate_errors.append(
                    {
                        "fit_mode": mode,
                        "orientation": orientation["name"],
                        "error": str(exc),
                    }
                )
    if not candidates:
        detail = "; ".join(item["error"] for item in candidate_errors[:3])
        raise PearPalDebugError(f"no transform candidate could be fitted: {detail}")

    selected = min(candidates, key=_candidate_sort_key)
    selected_loo = _leave_one_out(
        normalized,
        fit_mode=selected["fit_mode"],
        orientation=selected,
        flip_x_origin=flip_x_origin,
        flip_y_origin=flip_y_origin,
    )
    residual_ranking = _rank_landmark_diagnostics(
        selected["landmark_errors"],
        selected_loo["items"],
    )
    suggested_outliers, outlier_message = _suggest_outliers(residual_ranking)
    fit_results = _trimmed_fit_results(
        normalized,
        selected,
        residual_ranking,
        flip_x_origin=flip_x_origin,
        flip_y_origin=flip_y_origin,
    )

    warnings = list(selected["warnings"])
    if selected["fit_mode"] == "affine" and len(normalized) < 6:
        warnings.append(
            "affine was fitted with fewer than six landmarks; treat it as provisional"
        )
    if selected_loo["available_count"] < len(normalized):
        warnings.append(
            "leave-one-out is partially unavailable because a reduced fit was underdetermined"
        )
    if not suggested_outliers and selected["rmse"] > 0:
        warnings.append(outlier_message)

    result = {
        "version": 2,
        "source": "pearpal-public-debug",
        "world_id": str((metadata or {}).get("world_id") or ""),
        "map_name": str((metadata or {}).get("map_name") or "miraland"),
        "fit_mode_requested": fit_mode,
        "fit_mode_selected": selected["fit_mode"],
        "transform_type": selected["fit_mode"],
        "orientation": selected["orientation"],
        "swap_xy": selected["swap_xy"],
        "flip_x": selected["flip_x"],
        "flip_y": selected["flip_y"],
        "flip_x_origin": flip_x_origin,
        "flip_y_origin": flip_y_origin,
        "scale_x": selected.get("scale_x"),
        "scale_y": selected.get("scale_y"),
        "offset_x": selected.get("offset_x"),
        "offset_y": selected.get("offset_y"),
        "affine_matrix": selected.get("affine_matrix"),
        "rmse": selected["rmse"],
        "max_error": selected["max_error"],
        "loo_rmse": selected_loo["rmse"],
        "landmark_count": len(normalized),
        "warning": "; ".join(dict.fromkeys(warnings)),
        "warnings": list(dict.fromkeys(warnings)),
        "candidates": [
            {
                "fit_mode": candidate["fit_mode"],
                "orientation": candidate["orientation"],
                "swap_xy": candidate["swap_xy"],
                "flip_x": candidate["flip_x"],
                "flip_y": candidate["flip_y"],
                "scale_x": candidate.get("scale_x"),
                "scale_y": candidate.get("scale_y"),
                "offset_x": candidate.get("offset_x"),
                "offset_y": candidate.get("offset_y"),
                "affine_matrix": candidate.get("affine_matrix"),
                "rmse": candidate["rmse"],
                "max_error": candidate["max_error"],
                "loo_rmse": candidate["loo_rmse"],
                "selection_score": candidate["selection_score"],
                "warnings": candidate["warnings"],
            }
            for candidate in candidates
        ],
        "candidate_errors": candidate_errors,
        "landmark_errors": selected["landmark_errors"],
        "residual_ranking": residual_ranking,
        "leave_one_out": selected_loo,
        "suggested_outliers": suggested_outliers,
        "outlier_diagnostic": outlier_message,
        "fit_results": fit_results,
    }
    return result


def apply_pearpal_transform(
    web_x: float,
    web_y: float,
    transform: dict[str, Any],
) -> tuple[float, float]:
    try:
        flip_x_origin = float(transform.get("flip_x_origin", 0.0))
        flip_y_origin = float(transform.get("flip_y_origin", 0.0))
    except (TypeError, ValueError) as exc:
        raise PearPalDebugError("transform flip origins must be numeric") from exc
    source_x, source_y = _orient_web_point(
        web_x,
        web_y,
        swap_xy=bool(transform.get("swap_xy", False)),
        flip_x=bool(transform.get("flip_x", False)),
        flip_y=bool(transform.get("flip_y", False)),
        flip_x_origin=flip_x_origin,
        flip_y_origin=flip_y_origin,
    )
    transform_type = str(
        transform.get("transform_type")
        or transform.get("fit_mode_selected")
        or "axis-aligned"
    )
    if transform_type == "affine":
        matrix = transform.get("affine_matrix")
        if (
            not isinstance(matrix, list)
            or len(matrix) != 2
            or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
        ):
            raise PearPalDebugError("affine transform requires a 2x3 affine_matrix")
        try:
            return (
                float(matrix[0][0]) * source_x
                + float(matrix[0][1]) * source_y
                + float(matrix[0][2]),
                float(matrix[1][0]) * source_x
                + float(matrix[1][1]) * source_y
                + float(matrix[1][2]),
            )
        except (TypeError, ValueError) as exc:
            raise PearPalDebugError("affine_matrix values must be numeric") from exc

    values = {}
    for key in ("scale_x", "scale_y", "offset_x", "offset_y"):
        try:
            values[key] = float(transform[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise PearPalDebugError(f"transform is missing numeric {key}") from exc
    return (
        values["scale_x"] * source_x + values["offset_x"],
        values["scale_y"] * source_y + values["offset_y"],
    )


def load_landmarks(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PearPalDebugError(
            f"failed to read landmarks {source}: {type(exc).__name__}: {exc}"
        ) from exc
    if isinstance(payload, list):
        return payload, {}
    if isinstance(payload, dict) and isinstance(payload.get("landmarks"), list):
        return payload["landmarks"], payload
    raise PearPalDebugError("landmarks JSON must be a list or an object with landmarks")


def load_transform(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PearPalDebugError(
            f"failed to read transform {source}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PearPalDebugError("transform JSON root must be an object")
    return payload


def normalize_name(
    value: Any,
    aliases: dict[str, str] | None = None,
) -> str:
    normalized = _normalize_name_base(value)
    alias_table = dict(DEFAULT_NAME_ALIASES)
    if aliases:
        alias_table.update(aliases)
    normalized_aliases = {
        _normalize_name_base(source): _normalize_name_base(target)
        for source, target in alias_table.items()
    }
    return normalized_aliases.get(normalized, normalized)


def load_miraland_checkpoints(
    path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], Path]:
    source = (
        Path(path).expanduser().resolve()
        if path
        else Path(__file__).resolve().parents[2] / "assets" / "checkpoints.json"
    )
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PearPalDebugError(
            f"failed to read checkpoints {source}: {type(exc).__name__}: {exc}"
        ) from exc
    raw_checkpoints = payload.get("miraland") if isinstance(payload, dict) else None
    if not isinstance(raw_checkpoints, list):
        raise PearPalDebugError(
            "checkpoints schema changed: expected a miraland list"
        )

    from whimbox.map.convert import convert_GameLoc_to_PngMapPx

    checkpoints: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_checkpoints):
        if not isinstance(raw, dict):
            raise PearPalDebugError(f"miraland checkpoint {index} is not an object")
        name = str(raw.get("name") or "").strip()
        position = raw.get("position")
        if not name or not isinstance(position, (list, tuple)) or len(position) < 2:
            raise PearPalDebugError(
                f"miraland checkpoint {index} has invalid name/position"
            )
        game_x = _optional_finite_float(position[0])
        game_y = _optional_finite_float(position[1])
        if game_x is None or game_y is None:
            raise PearPalDebugError(
                f"miraland checkpoint {index} has non-finite game coordinates"
            )
        png_x, png_y = convert_GameLoc_to_PngMapPx(
            (game_x, game_y),
            "miraland",
            decimal=6,
        )
        checkpoints.append(
            {
                "checkpoint_index": index,
                "name": name,
                "map_name": "miraland",
                "game_x": game_x,
                "game_y": game_y,
                "png_x": float(png_x),
                "png_y": float(png_y),
            }
        )
    return checkpoints, source


def match_pearpal_checkpoints(
    pearpal_points: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    pearpal = [
        {
            **item,
            "_match_index": index,
            "_raw_name": str(item.get("name") or "").strip(),
        }
        for index, item in enumerate(pearpal_points)
        if item.get("is_candidate_visible", True)
        and _optional_finite_float(item.get("web_x")) is not None
        and _optional_finite_float(item.get("web_y")) is not None
    ]
    local = [
        {
            **item,
            "_match_index": index,
            "_raw_name": str(item.get("name") or "").strip(),
        }
        for index, item in enumerate(checkpoints)
    ]
    pearpal_remaining = {item["_match_index"] for item in pearpal}
    local_remaining = {item["_match_index"] for item in local}
    matches: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    pearpal_by_exact = _group_match_items(pearpal, key="_raw_name")
    local_by_exact = _group_match_items(local, key="_raw_name")
    for name in sorted(set(pearpal_by_exact) & set(local_by_exact)):
        pearpal_group = pearpal_by_exact[name]
        local_group = local_by_exact[name]
        if len(pearpal_group) == 1 and len(local_group) == 1:
            matches.append(
                _make_checkpoint_match(
                    pearpal_group[0],
                    local_group[0],
                    match_type="exact",
                    normalized_name=normalize_name(name, aliases),
                )
            )
        else:
            ambiguous.append(
                _ambiguous_match(
                    name,
                    pearpal_group,
                    local_group,
                    "exact name is not unique",
                )
            )
        pearpal_remaining.difference_update(
            item["_match_index"] for item in pearpal_group
        )
        local_remaining.difference_update(
            item["_match_index"] for item in local_group
        )

    remaining_pearpal = [
        item for item in pearpal if item["_match_index"] in pearpal_remaining
    ]
    remaining_local = [
        item for item in local if item["_match_index"] in local_remaining
    ]
    for item in remaining_pearpal:
        item["_normalized_name"] = normalize_name(item["_raw_name"], aliases)
    for item in remaining_local:
        item["_normalized_name"] = normalize_name(item["_raw_name"], aliases)
    pearpal_by_normalized = _group_match_items(
        remaining_pearpal,
        key="_normalized_name",
    )
    local_by_normalized = _group_match_items(
        remaining_local,
        key="_normalized_name",
    )
    for name in sorted(set(pearpal_by_normalized) & set(local_by_normalized)):
        pearpal_group = pearpal_by_normalized[name]
        local_group = local_by_normalized[name]
        if not name:
            continue
        if len(pearpal_group) == 1 and len(local_group) == 1:
            pearpal_item = pearpal_group[0]
            local_item = local_group[0]
            base_equal = (
                _normalize_name_base(pearpal_item["_raw_name"])
                == _normalize_name_base(local_item["_raw_name"])
            )
            matches.append(
                _make_checkpoint_match(
                    pearpal_item,
                    local_item,
                    match_type="normalized" if base_equal else "alias",
                    normalized_name=name,
                )
            )
        else:
            ambiguous.append(
                _ambiguous_match(
                    name,
                    pearpal_group,
                    local_group,
                    "normalized name is not unique",
                )
            )
        pearpal_remaining.difference_update(
            item["_match_index"] for item in pearpal_group
        )
        local_remaining.difference_update(
            item["_match_index"] for item in local_group
        )

    matches.sort(
        key=lambda item: (
            item["pearpal"]["name"],
            item["pearpal"]["id"],
        )
    )
    exact_matches = [item for item in matches if item["match_type"] == "exact"]
    normalized_matches = [
        item for item in matches if item["match_type"] != "exact"
    ]
    unmatched_pearpal = [
        _public_pearpal_match_item(item)
        for item in pearpal
        if item["_match_index"] in pearpal_remaining
    ]
    unmatched_checkpoints = [
        _public_checkpoint_match_item(item)
        for item in local
        if item["_match_index"] in local_remaining
    ]
    return {
        "total_pearpal": len(pearpal),
        "total_checkpoints": len(local),
        "matched_count": len(matches),
        "exact_match_count": len(exact_matches),
        "normalized_match_count": len(normalized_matches),
        "ambiguous_match_count": len(ambiguous),
        "unmatched_pearpal_count": len(unmatched_pearpal),
        "unmatched_checkpoint_count": len(unmatched_checkpoints),
        "exact_matches": exact_matches,
        "normalized_matches": normalized_matches,
        "unmatched_pearpal": unmatched_pearpal,
        "unmatched_checkpoints": unmatched_checkpoints,
        "ambiguous_matches": ambiguous,
        "matches": matches,
    }


def fit_pearpal_from_checkpoint_matches(
    matches: list[dict[str, Any]],
    *,
    world_id: str,
    catalog_id: str,
    holdout_ratio: float = 0.2,
    min_matches: int = 10,
) -> dict[str, Any]:
    if min_matches < 2:
        raise PearPalDebugError("min_matches must be at least 2")
    if len(matches) < min_matches:
        raise PearPalDebugError(
            f"checkpoint fit needs at least {min_matches} unambiguous matches; "
            f"found {len(matches)}"
        )
    if not 0 <= holdout_ratio < 1:
        raise PearPalDebugError("holdout_ratio must be in the range [0, 1)")

    train_matches, holdout_matches = _split_checkpoint_matches(
        matches,
        holdout_ratio,
    )
    if len(train_matches) < 2:
        raise PearPalDebugError("holdout ratio leaves fewer than two training matches")

    metadata = {
        "world_id": str(world_id),
        "catalog_id": str(catalog_id),
        "map_name": "miraland",
    }
    train_fit = fit_pearpal_transform(
        [_checkpoint_match_landmark(item) for item in train_matches],
        fit_mode="axis-aligned",
        flip_x_origin=0.0,
        flip_y_origin=0.0,
        metadata=metadata,
    )
    final_fit = fit_pearpal_transform(
        [_checkpoint_match_landmark(item) for item in matches],
        fit_mode="axis-aligned",
        flip_x_origin=0.0,
        flip_y_origin=0.0,
        metadata=metadata,
    )
    holdout_validation = _validate_checkpoint_matches(
        holdout_matches,
        train_fit,
    )
    train_validation = _validate_checkpoint_matches(
        train_matches,
        train_fit,
    )
    holdout_rmse = holdout_validation["rmse"]
    validation_errors = [
        value
        for value in (train_validation["rmse"], holdout_rmse)
        if value is not None
    ]
    validation_rmse = max(validation_errors) if validation_errors else None
    usable = (
        float(final_fit["rmse"]) < 20.0
        and (holdout_rmse is None or float(holdout_rmse) < 20.0)
    )
    warnings = list(final_fit["warnings"])
    for label, value in (
        ("final", final_fit["rmse"]),
        ("train", train_validation["rmse"]),
        ("holdout", holdout_rmse),
    ):
        if value is not None and float(value) > 50.0:
            warnings.append(f"{label} RMSE exceeds 50 PNG pixels")
    if final_fit["orientation"] != "no-flip":
        warnings.append(
            "checkpoint fit did not select no-flip; inspect coordinate assumptions"
        )
    warnings = list(dict.fromkeys(warnings))

    transform = {
        "version": 1,
        "source": "pearpal-checkpoint-fit",
        "target_coordinate": WHIMBOX_PNG_TARGET,
        "world_id": str(world_id),
        "catalog_id": str(catalog_id),
        "map_name": "miraland",
        "fit_mode": "axis-aligned",
        "fit_mode_selected": final_fit["fit_mode_selected"],
        "transform_type": final_fit["transform_type"],
        "orientation": final_fit["orientation"],
        "flip_x": final_fit["flip_x"],
        "flip_y": final_fit["flip_y"],
        "swap_xy": final_fit["swap_xy"],
        "flip_x_origin": final_fit["flip_x_origin"],
        "flip_y_origin": final_fit["flip_y_origin"],
        "scale_x": final_fit["scale_x"],
        "scale_y": final_fit["scale_y"],
        "offset_x": final_fit["offset_x"],
        "offset_y": final_fit["offset_y"],
        "rmse": final_fit["rmse"],
        "max_error": final_fit["max_error"],
        "train_rmse": train_validation["rmse"],
        "train_max_error": train_validation["max_error"],
        "holdout_rmse": holdout_rmse,
        "holdout_max_error": holdout_validation["max_error"],
        "validation_rmse": validation_rmse,
        "matches": len(matches),
        "training_matches": len(train_matches),
        "holdout_matches": len(holdout_matches),
        "holdout_ratio": holdout_ratio,
        "split_method": "sha256-name-id",
        "usable": usable,
        "warning": "; ".join(warnings),
        "warnings": warnings,
        "residual_ranking": final_fit["residual_ranking"],
        "leave_one_out": final_fit["leave_one_out"],
        "suggested_outliers": final_fit["suggested_outliers"],
        "outlier_diagnostic": final_fit["outlier_diagnostic"],
        "fit_results": final_fit["fit_results"],
    }
    role_by_id = {
        item["match_id"]: "training"
        for item in train_matches
    }
    role_by_id.update(
        {item["match_id"]: "holdout" for item in holdout_matches}
    )
    match_rows = []
    for item in matches:
        predicted_x, predicted_y = apply_pearpal_transform(
            float(item["pearpal"]["web_x"]),
            float(item["pearpal"]["web_y"]),
            train_fit,
        )
        error_x = predicted_x - float(item["checkpoint"]["png_x"])
        error_y = predicted_y - float(item["checkpoint"]["png_y"])
        match_rows.append(
            {
                "pearpal": item["pearpal"],
                "checkpoint": item["checkpoint"],
                "predicted_png_x": predicted_x,
                "predicted_png_y": predicted_y,
                "error_x": error_x,
                "error_y": error_y,
                "error_distance": math.hypot(error_x, error_y),
                "match_type": item["match_type"],
                "fit_role": role_by_id[item["match_id"]],
                "prediction_model": "training-split",
            }
        )
    match_rows.sort(key=lambda item: item["error_distance"], reverse=True)
    return {
        "transform": transform,
        "matches": match_rows,
        "training_validation": train_validation,
        "holdout_validation": holdout_validation,
    }


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path).expanduser().resolve()
    _write_json_atomic(target, payload)
    return target


def choose_center_tile(world: dict[str, Any]) -> tuple[int, int, int]:
    minimum, maximum = 3, 6
    zoom_range = str(world.get("zoom_range") or "")
    match = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*", zoom_range)
    if match:
        minimum = max(3, int(match.group(1)))
        maximum = min(6, int(match.group(2)))
    zoom = min(max(4, minimum), maximum) if minimum <= maximum else 4
    center = 2 ** max(0, zoom - 1)
    return zoom, center, center


def summarize_layers(
    world: dict[str, Any],
    language: str = "zh-cn",
) -> dict[str, Any]:
    layers = _decode_jsonish(world.get("layer_lists"))
    if not isinstance(layers, list):
        return {"count": 0, "items": []}
    items: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        value = (
            layer.get("id")
            or layer.get("layered_map_id")
            or layer.get("key")
            or layer.get("layer_configs")
            or index
        )
        items.append(
            {
                "id": str(value),
                "name": localized_text(layer.get("layer_name"), language),
                "layer_configs": str(layer.get("layer_configs") or ""),
                "left_top": str(layer.get("left_top") or ""),
                "right_bottom": str(layer.get("right_bottom") or ""),
                "sort_order": layer.get("sort_order"),
            }
        )
    return {"count": len(items), "items": items}


def _decode_api_json(data: bytes, label: str) -> dict[str, Any]:
    payload = _decode_json_bytes(data, label)
    if not isinstance(payload, dict):
        raise PearPalDebugError(f"{label} response is not an object")
    code = payload.get("code")
    if code != 0:
        raise PearPalDebugError(
            f"{label} public endpoint returned code={code} info={payload.get('info')}. "
            "Keep using LocalJsonProvider."
        )
    _reject_private_fields(payload)
    return payload


def _decode_json_bytes(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PearPalDebugError(f"{label} response is not valid UTF-8 JSON: {exc}") from exc


def _reject_forbidden_request_fields(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in FORBIDDEN_RESPONSE_KEYS:
                raise PearPalDebugError(f"refusing private request field: {key}")
            _reject_forbidden_request_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_forbidden_request_fields(item)


def _reject_private_fields(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in FORBIDDEN_RESPONSE_KEYS:
                raise PearPalDebugError(
                    f"public response unexpectedly contains private field {key}; refusing it"
                )
            _reject_private_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_private_fields(item)


def _read_varint(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if index >= len(data):
            raise PearPalDebugError("truncated Snappy length")
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
    raise PearPalDebugError("invalid Snappy length varint")


def _copy_snappy(output: bytearray, offset: int, length: int) -> None:
    if offset <= 0 or offset > len(output):
        raise PearPalDebugError(f"invalid Snappy copy offset: {offset}")
    for _ in range(length):
        output.append(output[-offset])


def _inspect_image(data: bytes) -> tuple[int | None, int | None, str]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.width, image.height, image.format or ""
    except Exception:
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return None, None, "WEBP"
        return None, None, ""


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _first_identifier(
    raw: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _decode_jsonish(value: Any) -> Any:
    decoded = value
    for _ in range(3):
        if not isinstance(decoded, str):
            break
        text = decoded.strip()
        if not text.startswith(("[", "{", '"')):
            break
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            break
    return decoded


def _language_keys(language: str) -> list[str]:
    normalized = language.lower().replace("_", "-")
    keys = [normalized]
    if normalized.startswith("zh-cn"):
        keys.extend(["zh-cn", "cn"])
    elif normalized.startswith("zh"):
        keys.extend(["zh-tw", "zh-cn"])
    elif normalized.startswith("en"):
        keys.append("en")
    keys.extend(["en", "zh-cn"])
    return list(dict.fromkeys(keys))


def _normalize_name_base(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    bracket_patterns = (
        r"\([^()]*\)",
        r"\[[^\[\]]*\]",
        r"\{[^{}]*\}",
        r"\u3010[^\u3010\u3011]*\u3011",
        r"\u300a[^\u300a\u300b]*\u300b",
        r"\u300c[^\u300c\u300d]*\u300d",
        r"\u300e[^\u300e\u300f]*\u300f",
    )
    for pattern in bracket_patterns:
        previous = None
        while previous != text:
            previous = text
            text = re.sub(pattern, "", text)
    return "".join(
        character
        for character in text
        if unicodedata.category(character)[:1] not in {"P", "S", "Z"}
    )


def _group_match_items(
    items: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get(key) or ""), []).append(item)
    return grouped


def _public_pearpal_match_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("source_id") or ""),
        "name": str(item.get("name") or ""),
        "web_x": _optional_finite_float(item.get("web_x")),
        "web_y": _optional_finite_float(item.get("web_y")),
    }


def _public_checkpoint_match_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkpoint_index": int(item.get("checkpoint_index", -1)),
        "name": str(item.get("name") or ""),
        "game_x": _optional_finite_float(item.get("game_x")),
        "game_y": _optional_finite_float(item.get("game_y")),
        "png_x": _optional_finite_float(item.get("png_x")),
        "png_y": _optional_finite_float(item.get("png_y")),
    }


def _make_checkpoint_match(
    pearpal: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    match_type: str,
    normalized_name: str,
) -> dict[str, Any]:
    pearpal_item = _public_pearpal_match_item(pearpal)
    checkpoint_item = _public_checkpoint_match_item(checkpoint)
    return {
        "match_id": (
            f"{pearpal_item['id']}:{checkpoint_item['checkpoint_index']}"
        ),
        "normalized_name": normalized_name,
        "match_type": match_type,
        "pearpal": pearpal_item,
        "checkpoint": checkpoint_item,
    }


def _ambiguous_match(
    normalized_name: str,
    pearpal: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "normalized_name": normalized_name,
        "reason": reason,
        "pearpal": [_public_pearpal_match_item(item) for item in pearpal],
        "checkpoints": [
            _public_checkpoint_match_item(item) for item in checkpoints
        ],
    }


def _split_checkpoint_matches(
    matches: list[dict[str, Any]],
    holdout_ratio: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if holdout_ratio <= 0 or len(matches) <= 2:
        return list(matches), []
    holdout_count = max(1, int(round(len(matches) * holdout_ratio)))
    holdout_count = min(holdout_count, len(matches) - 2)
    ranked = sorted(
        matches,
        key=lambda item: hashlib.sha256(
            item["match_id"].encode("utf-8")
        ).hexdigest(),
    )
    holdout_ids = {item["match_id"] for item in ranked[:holdout_count]}
    training = [
        item for item in matches if item["match_id"] not in holdout_ids
    ]
    holdout = [
        item for item in matches if item["match_id"] in holdout_ids
    ]
    return training, holdout


def _checkpoint_match_landmark(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["pearpal"]["name"],
        "web_x": item["pearpal"]["web_x"],
        "web_y": item["pearpal"]["web_y"],
        "game_image_x": item["checkpoint"]["png_x"],
        "game_image_y": item["checkpoint"]["png_y"],
    }


def _validate_checkpoint_matches(
    matches: list[dict[str, Any]],
    transform: dict[str, Any],
) -> dict[str, Any]:
    if not matches:
        return {
            "count": 0,
            "rmse": None,
            "max_error": None,
            "items": [],
        }
    items: list[dict[str, Any]] = []
    squared_error_sum = 0.0
    max_error = 0.0
    for item in matches:
        predicted_x, predicted_y = apply_pearpal_transform(
            float(item["pearpal"]["web_x"]),
            float(item["pearpal"]["web_y"]),
            transform,
        )
        error_x = predicted_x - float(item["checkpoint"]["png_x"])
        error_y = predicted_y - float(item["checkpoint"]["png_y"])
        error = math.hypot(error_x, error_y)
        squared_error_sum += error * error
        max_error = max(max_error, error)
        items.append(
            {
                "match_id": item["match_id"],
                "name": item["pearpal"]["name"],
                "predicted_png_x": predicted_x,
                "predicted_png_y": predicted_y,
                "actual_png_x": item["checkpoint"]["png_x"],
                "actual_png_y": item["checkpoint"]["png_y"],
                "error_x": error_x,
                "error_y": error_y,
                "error_distance": error,
            }
        )
    items.sort(key=lambda item: item["error_distance"], reverse=True)
    return {
        "count": len(matches),
        "rmse": math.sqrt(squared_error_sum / len(matches)),
        "max_error": max_error,
        "items": items,
    }


def _normalize_landmark(item: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise PearPalDebugError(f"landmark {index} must be an object")
    normalized = {"name": str(item.get("name") or f"landmark_{index + 1}")}
    for key in ("web_x", "web_y", "game_image_x", "game_image_y"):
        try:
            value = float(item[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise PearPalDebugError(f"landmark {index} has invalid {key}") from exc
        if not math.isfinite(value):
            raise PearPalDebugError(f"landmark {index} has non-finite {key}")
        normalized[key] = value
    return normalized


def _fit_transform_candidate(
    landmarks: list[dict[str, Any]],
    *,
    fit_mode: str,
    orientation: dict[str, Any],
    flip_x_origin: float,
    flip_y_origin: float,
) -> dict[str, Any]:
    if fit_mode == "axis-aligned" and len(landmarks) < 2:
        raise PearPalDebugError("axis-aligned fit requires at least two landmarks")
    if fit_mode == "affine" and len(landmarks) < 3:
        raise PearPalDebugError("affine fit requires at least three landmarks")

    source = [
        _orient_web_point(
            float(item["web_x"]),
            float(item["web_y"]),
            swap_xy=bool(orientation["swap_xy"]),
            flip_x=bool(orientation["flip_x"]),
            flip_y=bool(orientation["flip_y"]),
            flip_x_origin=flip_x_origin,
            flip_y_origin=flip_y_origin,
        )
        for item in landmarks
    ]
    web_x = [item[0] for item in source]
    web_y = [item[1] for item in source]
    game_x = [float(item["game_image_x"]) for item in landmarks]
    game_y = [float(item["game_image_y"]) for item in landmarks]
    candidate: dict[str, Any] = {
        "fit_mode": fit_mode,
        "orientation": orientation["name"],
        "swap_xy": bool(orientation["swap_xy"]),
        "flip_x": bool(orientation["flip_x"]),
        "flip_y": bool(orientation["flip_y"]),
        "warnings": [],
    }
    if fit_mode == "axis-aligned":
        scale_x, offset_x = _fit_line(web_x, game_x, "oriented web x")
        scale_y, offset_y = _fit_line(web_y, game_y, "oriented web y")
        candidate.update(
            {
                "scale_x": scale_x,
                "scale_y": scale_y,
                "offset_x": offset_x,
                "offset_y": offset_y,
                "affine_matrix": None,
            }
        )
        if scale_x < 0:
            candidate["warnings"].append(
                "negative scale_x: the x-axis may run in the opposite direction; "
                "consider the equivalent flip_x orientation"
            )
        if scale_y < 0:
            candidate["warnings"].append(
                "negative scale_y: the y-axis may run in the opposite direction; "
                "consider the equivalent flip_y orientation"
            )
    else:
        design = np.asarray([[x, y, 1.0] for x, y in source], dtype=float)
        if int(np.linalg.matrix_rank(design)) < 3:
            raise PearPalDebugError(
                "affine fit requires at least three non-collinear landmarks"
            )
        target_x = np.asarray(game_x, dtype=float)
        target_y = np.asarray(game_y, dtype=float)
        coefficient_x = np.linalg.lstsq(design, target_x, rcond=None)[0]
        coefficient_y = np.linalg.lstsq(design, target_y, rcond=None)[0]
        matrix = [
            [float(value) for value in coefficient_x],
            [float(value) for value in coefficient_y],
        ]
        candidate.update(
            {
                "scale_x": None,
                "scale_y": None,
                "offset_x": None,
                "offset_y": None,
                "affine_matrix": matrix,
            }
        )
        if len(landmarks) < 6:
            candidate["warnings"].append(
                "affine fit has fewer than six landmarks and may be unstable"
            )
        determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        if determinant < 0:
            candidate["warnings"].append(
                "affine determinant is negative; the fitted axes include a reflection"
            )

    errors: list[dict[str, Any]] = []
    squared_error_sum = 0.0
    max_error = 0.0
    for index, item in enumerate(landmarks):
        predicted_x, predicted_y = _predict_candidate(
            candidate,
            float(item["web_x"]),
            float(item["web_y"]),
            flip_x_origin=flip_x_origin,
            flip_y_origin=flip_y_origin,
        )
        error_x = predicted_x - float(item["game_image_x"])
        error_y = predicted_y - float(item["game_image_y"])
        error = math.hypot(error_x, error_y)
        squared_error_sum += error * error
        max_error = max(max_error, error)
        errors.append(
            {
                "index": index,
                "name": item["name"],
                "actual_game_image_x": float(item["game_image_x"]),
                "actual_game_image_y": float(item["game_image_y"]),
                "predicted_game_image_x": predicted_x,
                "predicted_game_image_y": predicted_y,
                "error_x": error_x,
                "error_y": error_y,
                "error": error,
            }
        )
    candidate.update(
        {
            "rmse": math.sqrt(squared_error_sum / len(landmarks)),
            "max_error": max_error,
            "landmark_errors": errors,
        }
    )
    return candidate


def _transform_orientations() -> list[dict[str, Any]]:
    return [
        {"name": "no-flip", "swap_xy": False, "flip_x": False, "flip_y": False},
        {"name": "flip-x", "swap_xy": False, "flip_x": True, "flip_y": False},
        {"name": "flip-y", "swap_xy": False, "flip_x": False, "flip_y": True},
        {
            "name": "flip-x+flip-y",
            "swap_xy": False,
            "flip_x": True,
            "flip_y": True,
        },
        {"name": "swap-xy", "swap_xy": True, "flip_x": False, "flip_y": False},
        {
            "name": "swap-xy+flip-x",
            "swap_xy": True,
            "flip_x": True,
            "flip_y": False,
        },
        {
            "name": "swap-xy+flip-y",
            "swap_xy": True,
            "flip_x": False,
            "flip_y": True,
        },
        {
            "name": "swap-xy+flip-x+flip-y",
            "swap_xy": True,
            "flip_x": True,
            "flip_y": True,
        },
    ]


def _orient_web_point(
    web_x: float,
    web_y: float,
    *,
    swap_xy: bool,
    flip_x: bool,
    flip_y: bool,
    flip_x_origin: float,
    flip_y_origin: float,
) -> tuple[float, float]:
    if swap_xy:
        source_x, source_y = web_y, web_x
        source_x_origin, source_y_origin = flip_y_origin, flip_x_origin
    else:
        source_x, source_y = web_x, web_y
        source_x_origin, source_y_origin = flip_x_origin, flip_y_origin
    if flip_x:
        source_x = source_x_origin - source_x
    if flip_y:
        source_y = source_y_origin - source_y
    return source_x, source_y


def _predict_candidate(
    candidate: dict[str, Any],
    web_x: float,
    web_y: float,
    *,
    flip_x_origin: float,
    flip_y_origin: float,
) -> tuple[float, float]:
    source_x, source_y = _orient_web_point(
        web_x,
        web_y,
        swap_xy=bool(candidate["swap_xy"]),
        flip_x=bool(candidate["flip_x"]),
        flip_y=bool(candidate["flip_y"]),
        flip_x_origin=flip_x_origin,
        flip_y_origin=flip_y_origin,
    )
    if candidate["fit_mode"] == "affine":
        matrix = candidate["affine_matrix"]
        return (
            matrix[0][0] * source_x + matrix[0][1] * source_y + matrix[0][2],
            matrix[1][0] * source_x + matrix[1][1] * source_y + matrix[1][2],
        )
    return (
        candidate["scale_x"] * source_x + candidate["offset_x"],
        candidate["scale_y"] * source_y + candidate["offset_y"],
    )


def _leave_one_out(
    landmarks: list[dict[str, Any]],
    *,
    fit_mode: str,
    orientation: dict[str, Any],
    flip_x_origin: float,
    flip_y_origin: float,
) -> dict[str, Any]:
    orientation_spec = {
        "name": orientation.get("name", orientation.get("orientation", "unknown")),
        "swap_xy": bool(orientation["swap_xy"]),
        "flip_x": bool(orientation["flip_x"]),
        "flip_y": bool(orientation["flip_y"]),
    }
    items: list[dict[str, Any]] = []
    squared_error_sum = 0.0
    available_count = 0
    for index, omitted in enumerate(landmarks):
        remaining = [item for item_index, item in enumerate(landmarks) if item_index != index]
        try:
            candidate = _fit_transform_candidate(
                remaining,
                fit_mode=fit_mode,
                orientation=orientation_spec,
                flip_x_origin=flip_x_origin,
                flip_y_origin=flip_y_origin,
            )
            predicted_x, predicted_y = _predict_candidate(
                candidate,
                float(omitted["web_x"]),
                float(omitted["web_y"]),
                flip_x_origin=flip_x_origin,
                flip_y_origin=flip_y_origin,
            )
            error_x = predicted_x - float(omitted["game_image_x"])
            error_y = predicted_y - float(omitted["game_image_y"])
            error = math.hypot(error_x, error_y)
            squared_error_sum += error * error
            available_count += 1
            items.append(
                {
                    "index": index,
                    "name": omitted["name"],
                    "status": "ok",
                    "predicted_game_image_x": predicted_x,
                    "predicted_game_image_y": predicted_y,
                    "error_x": error_x,
                    "error_y": error_y,
                    "error": error,
                }
            )
        except PearPalDebugError as exc:
            items.append(
                {
                    "index": index,
                    "name": omitted["name"],
                    "status": "unavailable",
                    "error": None,
                    "reason": str(exc),
                }
            )
    return {
        "fit_mode": fit_mode,
        "orientation": orientation_spec["name"],
        "available_count": available_count,
        "landmark_count": len(landmarks),
        "rmse": (
            math.sqrt(squared_error_sum / available_count)
            if available_count
            else None
        ),
        "items": items,
    }


def _candidate_selection_score(candidate: dict[str, Any]) -> float:
    base = (
        float(candidate["loo_rmse"])
        if candidate.get("loo_rmse") is not None
        else float(candidate["rmse"]) * 1.5
    )
    if candidate["fit_mode"] == "affine":
        base *= 1.05
        if candidate["loo_available_count"] < 6:
            base *= 1.05
    return base


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    negative_scales = sum(
        1
        for key in ("scale_x", "scale_y")
        if candidate.get(key) is not None and float(candidate[key]) < 0
    )
    orientation_complexity = (
        int(candidate["swap_xy"])
        + int(candidate["flip_x"])
        + int(candidate["flip_y"])
    )
    return (
        round(float(candidate["selection_score"]), 6),
        negative_scales,
        0 if candidate["fit_mode"] == "axis-aligned" else 1,
        orientation_complexity,
        candidate["orientation"],
    )


def _rank_landmark_diagnostics(
    residuals: list[dict[str, Any]],
    leave_one_out: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    loo_by_index = {item["index"]: item for item in leave_one_out}
    ranking: list[dict[str, Any]] = []
    for residual in residuals:
        loo = loo_by_index.get(residual["index"], {})
        loo_error = loo.get("error") if loo.get("status") == "ok" else None
        diagnostic_score = (
            float(loo_error)
            if loo_error is not None
            else float(residual["error"])
        )
        ranking.append(
            {
                **residual,
                "leave_one_out_error": loo_error,
                "leave_one_out_status": loo.get("status", "unavailable"),
                "diagnostic_score": diagnostic_score,
            }
        )
    ranking.sort(key=lambda item: item["diagnostic_score"], reverse=True)
    for rank, item in enumerate(ranking, start=1):
        item["rank"] = rank
    return ranking


def _suggest_outliers(
    ranking: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if len(ranking) < 3:
        return [], "too few landmarks for reliable outlier suggestions"
    scores = [float(item["diagnostic_score"]) for item in ranking]
    median = statistics.median(scores)
    deviations = [abs(score - median) for score in scores]
    mad = statistics.median(deviations)
    robust_sigma = 1.4826 * mad
    robust_threshold = median + 2.5 * robust_sigma
    relative_threshold = median * 1.75 if median > 0 else robust_threshold
    threshold = max(robust_threshold, relative_threshold)
    suggested = [item for item in ranking if item["diagnostic_score"] > threshold][:2]
    if not suggested and scores[0] > 0 and scores[0] >= max(median * 1.5, scores[1] * 1.2):
        suggested = [ranking[0]]
    output = [
        {
            "name": item["name"],
            "rank": item["rank"],
            "diagnostic_score": item["diagnostic_score"],
            "residual_error": item["error"],
            "leave_one_out_error": item["leave_one_out_error"],
            "reason": "high residual/leave-one-out error",
        }
        for item in suggested
    ]
    if output:
        message = (
            "suggested outliers exceed the robust/relative error threshold; "
            "recheck their game_image coordinates before deleting them"
        )
    else:
        message = (
            "no isolated outlier dominates; large errors may indicate multiple bad "
            "landmarks or the wrong transform model"
        )
    return output, message


def _trimmed_fit_results(
    landmarks: list[dict[str, Any]],
    selected: dict[str, Any],
    ranking: list[dict[str, Any]],
    *,
    flip_x_origin: float,
    flip_y_origin: float,
) -> dict[str, Any]:
    results = {
        "all_points": _fit_result_summary(selected, [], []),
    }
    orientation = {
        "name": selected["orientation"],
        "swap_xy": selected["swap_xy"],
        "flip_x": selected["flip_x"],
        "flip_y": selected["flip_y"],
    }
    for drop_count in (1, 2):
        key = f"drop_worst_{drop_count}"
        excluded_indexes = {item["index"] for item in ranking[:drop_count]}
        excluded = [item for index, item in enumerate(landmarks) if index in excluded_indexes]
        remaining = [item for index, item in enumerate(landmarks) if index not in excluded_indexes]
        try:
            candidate = _fit_transform_candidate(
                remaining,
                fit_mode=selected["fit_mode"],
                orientation=orientation,
                flip_x_origin=flip_x_origin,
                flip_y_origin=flip_y_origin,
            )
            excluded_predictions = []
            for item in excluded:
                predicted_x, predicted_y = _predict_candidate(
                    candidate,
                    float(item["web_x"]),
                    float(item["web_y"]),
                    flip_x_origin=flip_x_origin,
                    flip_y_origin=flip_y_origin,
                )
                error_x = predicted_x - float(item["game_image_x"])
                error_y = predicted_y - float(item["game_image_y"])
                excluded_predictions.append(
                    {
                        "name": item["name"],
                        "predicted_game_image_x": predicted_x,
                        "predicted_game_image_y": predicted_y,
                        "error_x": error_x,
                        "error_y": error_y,
                        "error": math.hypot(error_x, error_y),
                    }
                )
            results[key] = _fit_result_summary(
                candidate,
                [item["name"] for item in excluded],
                excluded_predictions,
            )
        except PearPalDebugError as exc:
            results[key] = {
                "status": "unavailable",
                "excluded_landmarks": [item["name"] for item in excluded],
                "reason": str(exc),
            }
    return results


def _fit_result_summary(
    candidate: dict[str, Any],
    excluded_landmarks: list[str],
    excluded_predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "ok",
        "fit_mode": candidate["fit_mode"],
        "orientation": candidate["orientation"],
        "landmark_count": len(candidate["landmark_errors"]),
        "excluded_landmarks": excluded_landmarks,
        "rmse": candidate["rmse"],
        "max_error": candidate["max_error"],
        "scale_x": candidate.get("scale_x"),
        "scale_y": candidate.get("scale_y"),
        "offset_x": candidate.get("offset_x"),
        "offset_y": candidate.get("offset_y"),
        "affine_matrix": candidate.get("affine_matrix"),
        "excluded_predictions": excluded_predictions,
    }


def _fit_line(source: list[float], target: list[float], label: str) -> tuple[float, float]:
    source_mean = sum(source) / len(source)
    target_mean = sum(target) / len(target)
    denominator = sum((value - source_mean) ** 2 for value in source)
    if denominator <= 1e-12:
        raise PearPalDebugError(f"landmarks need at least two distinct {label} values")
    scale = sum(
        (source_value - source_mean) * (target_value - target_mean)
        for source_value, target_value in zip(source, target)
    ) / denominator
    return scale, target_mean - scale * source_mean


def _optional_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validate_client_id(value: str) -> str:
    if not re.fullmatch(r"\d{3,8}", value):
        raise PearPalDebugError("public client id must contain 3-8 digits")
    return value


def _validate_identifier(value: str, label: str) -> str:
    text = str(value).strip()
    if not text or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", text):
        raise PearPalDebugError(f"invalid {label}: {value}")
    return text


def _validate_resource_name(value: str) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", text):
        raise PearPalDebugError(f"invalid public map resource name: {value}")
    return text


def _safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return result.strip(".-") or "default"


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
