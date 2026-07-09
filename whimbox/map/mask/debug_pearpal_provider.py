from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .pearpal_debug import (
    PearPalDebugError,
    PearPalPublicDebugClient,
    WHIMBOX_PNG_TARGET,
    apply_pearpal_transform,
    choose_center_tile,
    default_cache_dir,
    expand_stage_spawners,
    extract_api_list,
    find_catalog,
    fit_pearpal_from_checkpoint_matches,
    fit_pearpal_transform,
    flatten_catalogs,
    inspect_raw_spawner,
    load_miraland_checkpoints,
    load_landmarks,
    load_transform,
    localized_text,
    match_pearpal_checkpoints,
    normalize_spawner,
    raw_spawner_name,
    spawner_catalog_id,
    spawner_world_id,
    summarize_layers,
    write_json,
)


DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            return _discover(args)
        if args.command == "fetch":
            return _fetch(args)
        if args.command == "transform":
            return _transform(args)
        if args.command == "fit-from-checkpoints":
            return _fit_from_checkpoints(args)
        if args.command == "export-local-points":
            return _export_local_points(args)
        parser.print_help()
        return 2
    except PearPalDebugError as exc:
        print(f"PearPal debug command failed: {exc}", file=sys.stderr, flush=True)
        print(
            "No official provider or RPC was changed; keep using LocalJsonProvider.",
            file=sys.stderr,
            flush=True,
        )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only anonymous discovery tools for public PearPal map resources."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        parents=[_network_parent()],
        help="read public world/catalog metadata and validate one tile",
    )
    discover.add_argument("--world-id", default="1")
    discover.add_argument("--json", action="store_true", help="print a JSON report")

    fetch = subparsers.add_parser(
        "fetch",
        parents=[_network_parent()],
        help="fetch one public world/catalog spawner response",
    )
    fetch.add_argument("--world-id", required=True)
    fetch.add_argument("--catalog-id", required=True)
    fetch.add_argument("--limit", type=_bounded_limit, default=DEFAULT_LIMIT)
    fetch.add_argument(
        "--output-format",
        choices=("raw", "normalized"),
        default="normalized",
    )
    fetch.add_argument(
        "--inspect-fields",
        action="store_true",
        help="include normalized aliases and complete key lists for raw spawners",
    )
    fetch.add_argument(
        "--name-contains",
        help="temporarily search raw localized names/descriptions",
    )
    fetch.add_argument("--output", help="optional JSON report path")

    transform = subparsers.add_parser(
        "transform",
        help="fit PearPal web coordinates to Whimbox game image coordinates",
    )
    transform.add_argument("--landmarks", required=True)
    transform.add_argument(
        "--fit-mode",
        choices=("axis-aligned", "affine", "auto"),
        default="auto",
    )
    transform.add_argument("--flip-x-origin", type=float)
    transform.add_argument("--flip-y-origin", type=float)
    transform.add_argument(
        "--output",
        default="pearpal_to_game_transform.json",
    )

    checkpoint_fit = subparsers.add_parser(
        "fit-from-checkpoints",
        parents=[_network_parent()],
        help="fit public PearPal coordinates to Whimbox full-resolution PNG coordinates",
    )
    checkpoint_fit.add_argument("--world-id", required=True)
    checkpoint_fit.add_argument("--catalog-id", required=True)
    checkpoint_fit.add_argument(
        "--checkpoints",
        help="optional checkpoints.json path; defaults to Whimbox assets",
    )
    checkpoint_fit.add_argument(
        "--holdout-ratio",
        type=_holdout_ratio,
        default=0.2,
    )
    checkpoint_fit.add_argument(
        "--min-matches",
        type=_minimum_matches,
        default=10,
    )
    checkpoint_fit.add_argument(
        "--output",
        default="pearpal_to_png_transform.json",
    )
    checkpoint_fit.add_argument(
        "--matched-output",
        default="pearpal_checkpoint_matches.json",
    )

    export = subparsers.add_parser(
        "export-local-points",
        parents=[_network_parent()],
        help="export transformed candidates for manual LocalJsonProvider validation",
    )
    export.add_argument("--world-id", required=True)
    export.add_argument("--catalog-id", required=True)
    export.add_argument("--transform", required=True)
    export.add_argument("--limit", type=_bounded_limit, default=DEFAULT_LIMIT)
    export.add_argument("--map-name")
    export.add_argument("--output")
    return parser


def _network_parent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--region", choices=("cn", "oversea"), default="cn")
    parser.add_argument("--language", default="zh-cn")
    parser.add_argument(
        "--client-id",
        help="current public numeric client id; normally extracted from the public bundle",
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument("--no-cache", action="store_true")
    cache_group.add_argument("--refresh", action="store_true")
    return parser


def _client(args: argparse.Namespace) -> PearPalPublicDebugClient:
    return PearPalPublicDebugClient(
        region=args.region,
        language=args.language,
        client_id=args.client_id,
        no_cache=args.no_cache,
        refresh=args.refresh,
    )


def _discover(args: argparse.Namespace) -> int:
    client = _client(args)
    world_response, world_fetch = client.fetch_world_config()
    worlds = extract_api_list(world_response, "world config")
    world = _find_world(worlds, args.world_id)
    catalog_response, catalog_fetch = client.fetch_catalog(args.world_id)
    catalogs = flatten_catalogs(catalog_response, args.language)

    tile: dict[str, Any] = {"status": "skipped", "reason": "world has no tile resource"}
    resource = str(world.get("map_resource_url") or "")
    if resource:
        zoom, tile_x, tile_y = choose_center_tile(world)
        tile = client.validate_single_tile(
            map_resource_url=resource,
            zoom=zoom,
            tile_x=tile_x,
            tile_y=tile_y,
        )

    report = {
        "anonymous": True,
        "region": args.region,
        "language": args.language,
        "cache_dir": str(default_cache_dir()),
        "world_cache_hit": world_fetch.cache_hit,
        "catalog_cache_hit": catalog_fetch.cache_hit,
        "world_count": len(worlds),
        "catalog_count": len(catalogs),
        "worlds": [_world_summary(item, args.language) for item in worlds if isinstance(item, dict)],
        "catalogs": [_catalog_summary(item) for item in catalogs],
        "tile": tile,
    }
    if args.json:
        _print_json(report)
    else:
        _print_discovery(report)
    return 0


def _fetch(args: argparse.Namespace) -> int:
    client = _client(args)
    prepared = _prepare_catalog_fetch(
        client,
        world_id=args.world_id,
        catalog_id=args.catalog_id,
        language=args.language,
        limit=args.limit,
        name_contains=args.name_contains,
    )
    report: dict[str, Any] = {
        "anonymous": True,
        "region": args.region,
        **prepared["summary"],
        "output_limit": args.limit,
        "output_format": args.output_format,
        "items": (
            prepared["limited_raw"]
            if args.output_format == "raw"
            else prepared["limited_normalized"]
        ),
    }
    if args.inspect_fields:
        report["raw_field_summary"] = _raw_field_summary(
            prepared["world_filtered_raw"]
        )
        report["raw_field_inspection"] = [
            inspect_raw_spawner(item, args.language)
            for item in prepared["world_filtered_raw"][: args.limit]
        ]
    _print_fetch_summary(report, prepared["limited_normalized"][:20])
    if args.inspect_fields:
        _print_field_inspection(report["raw_field_summary"])
    if args.output:
        output = write_json(args.output, report)
        print(f"JSON report written: {output}", flush=True)
    return 0


def _transform(args: argparse.Namespace) -> int:
    landmarks, metadata = load_landmarks(args.landmarks)
    if not landmarks:
        raise PearPalDebugError("landmarks JSON is empty")
    flip_x_origin = _resolve_flip_origin(
        args.flip_x_origin,
        metadata,
        "flip_x_origin",
        landmarks,
        "web_x",
    )
    flip_y_origin = _resolve_flip_origin(
        args.flip_y_origin,
        metadata,
        "flip_y_origin",
        landmarks,
        "web_y",
    )
    transform = fit_pearpal_transform(
        landmarks,
        fit_mode=args.fit_mode,
        flip_x_origin=flip_x_origin,
        flip_y_origin=flip_y_origin,
        metadata=metadata,
    )
    output = write_json(args.output, transform)
    print(
        "PearPal transform fitted: "
        f"mode={transform['fit_mode_selected']} "
        f"orientation={transform['orientation']} "
        f"swap_xy={transform['swap_xy']} "
        f"flip_x={transform['flip_x']} flip_y={transform['flip_y']}",
        flush=True,
    )
    if transform["fit_mode_selected"] == "axis-aligned":
        print(
            f"  scale=({transform['scale_x']:.12g}, {transform['scale_y']:.12g}) "
            f"offset=({transform['offset_x']:.6f}, {transform['offset_y']:.6f})",
            flush=True,
        )
    else:
        print(f"  affine_matrix={transform['affine_matrix']}", flush=True)
    print(
        f"  rmse={transform['rmse']:.6f} max_error={transform['max_error']:.6f} "
        f"loo_rmse={_format_optional_float(transform['loo_rmse'])} "
        f"landmarks={transform['landmark_count']}",
        flush=True,
    )
    print("  Residual ranking:", flush=True)
    for item in transform["residual_ranking"]:
        print(
            f"    #{item['rank']} {item['name']}: "
            f"residual={item['error']:.4f} "
            f"leave_one_out={_format_optional_float(item['leave_one_out_error'])} "
            f"score={item['diagnostic_score']:.4f}",
            flush=True,
        )
    print("  Leave-one-out:", flush=True)
    for item in transform["leave_one_out"]["items"]:
        if item["status"] == "ok":
            print(
                f"    {item['name']}: error={item['error']:.4f} "
                f"delta=({item['error_x']:.4f}, {item['error_y']:.4f})",
                flush=True,
            )
        else:
            print(
                f"    {item['name']}: unavailable ({item['reason']})",
                flush=True,
            )
    if transform["suggested_outliers"]:
        print("  Suggested outliers:", flush=True)
        for item in transform["suggested_outliers"]:
            print(
                f"    {item['name']}: score={item['diagnostic_score']:.4f} "
                f"reason={item['reason']}",
                flush=True,
            )
    else:
        print(f"  Suggested outliers: none ({transform['outlier_diagnostic']})", flush=True)
    print("  Fit comparison:", flush=True)
    for key in ("all_points", "drop_worst_1", "drop_worst_2"):
        item = transform["fit_results"][key]
        if item["status"] == "ok":
            print(
                f"    {key}: landmarks={item['landmark_count']} "
                f"rmse={item['rmse']:.6f} max_error={item['max_error']:.6f} "
                f"excluded={item['excluded_landmarks']}",
                flush=True,
            )
        else:
            print(
                f"    {key}: unavailable ({item['reason']})",
                flush=True,
            )
    for warning in transform["warnings"]:
        print(f"  warning: {warning}", flush=True)
    print(f"Transform written: {output}", flush=True)
    return 0


def _fit_from_checkpoints(args: argparse.Namespace) -> int:
    client = _client(args)
    prepared = _prepare_catalog_fetch(
        client,
        world_id=args.world_id,
        catalog_id=args.catalog_id,
        language=args.language,
        limit=MAX_LIMIT,
        name_contains=None,
    )
    fetch_summary = prepared["summary"]
    if fetch_summary["catalog_filter_status"] == "unresolved":
        raise PearPalDebugError(
            "catalog_filter_unresolved: refusing checkpoint fit because the "
            "public spawner response is not catalog-clean"
        )
    candidates = [
        item
        for item in prepared["limited_normalized"]
        if item["is_candidate_visible"]
    ]
    checkpoints, checkpoint_path = load_miraland_checkpoints(args.checkpoints)
    matching = match_pearpal_checkpoints(candidates, checkpoints)
    report: dict[str, Any] = {
        "version": 1,
        "source": "pearpal-checkpoint-fit",
        "target_coordinate": WHIMBOX_PNG_TARGET,
        "world_id": str(args.world_id),
        "catalog_id": str(args.catalog_id),
        "catalog_name": fetch_summary["catalog_name"],
        "catalog_declared_count": fetch_summary["catalog_declared_count"],
        "catalog_filter_status": fetch_summary["catalog_filter_status"],
        "checkpoints_path": str(checkpoint_path),
        "total_pearpal": matching["total_pearpal"],
        "total_checkpoints": matching["total_checkpoints"],
        "matched_count": matching["matched_count"],
        "exact_match_count": matching["exact_match_count"],
        "normalized_match_count": matching["normalized_match_count"],
        "ambiguous_match_count": matching["ambiguous_match_count"],
        "unmatched_pearpal_count": matching["unmatched_pearpal_count"],
        "unmatched_checkpoint_count": matching["unmatched_checkpoint_count"],
        "exact_matches": matching["exact_matches"],
        "normalized_matches": matching["normalized_matches"],
        "unmatched_pearpal": matching["unmatched_pearpal"],
        "unmatched_checkpoints": matching["unmatched_checkpoints"],
        "ambiguous_matches": matching["ambiguous_matches"],
    }
    if matching["matched_count"] < args.min_matches:
        report["fit_error"] = (
            f"minimum matches not met: {matching['matched_count']} "
            f"< {args.min_matches}"
        )
        matched_output = write_json(args.matched_output, report)
        raise PearPalDebugError(
            f"{report['fit_error']}; match report written to {matched_output}"
        )

    fitted = fit_pearpal_from_checkpoint_matches(
        matching["matches"],
        world_id=str(args.world_id),
        catalog_id=str(args.catalog_id),
        holdout_ratio=args.holdout_ratio,
        min_matches=args.min_matches,
    )
    transform = fitted["transform"]
    report.update(
        {
            "fit": {
                "fit_mode": transform["fit_mode"],
                "orientation": transform["orientation"],
                "scale_x": transform["scale_x"],
                "scale_y": transform["scale_y"],
                "offset_x": transform["offset_x"],
                "offset_y": transform["offset_y"],
                "rmse": transform["rmse"],
                "max_error": transform["max_error"],
                "train_rmse": transform["train_rmse"],
                "train_max_error": transform["train_max_error"],
                "holdout_rmse": transform["holdout_rmse"],
                "holdout_max_error": transform["holdout_max_error"],
                "usable": transform["usable"],
                "warnings": transform["warnings"],
            },
            "training_validation": fitted["training_validation"],
            "holdout_validation": fitted["holdout_validation"],
            "matches": fitted["matches"],
        }
    )
    transform_output = write_json(args.output, transform)
    matched_output = write_json(args.matched_output, report)

    print(
        "PearPal checkpoint fit: "
        f"world={args.world_id} catalog={args.catalog_id} "
        f"catalog_name={fetch_summary['catalog_name']}",
        flush=True,
    )
    print(
        f"  matches={matching['matched_count']} "
        f"exact={matching['exact_match_count']} "
        f"normalized_or_alias={matching['normalized_match_count']} "
        f"ambiguous={matching['ambiguous_match_count']}",
        flush=True,
    )
    print(
        f"  unmatched_pearpal={matching['unmatched_pearpal_count']} "
        f"unmatched_checkpoints={matching['unmatched_checkpoint_count']}",
        flush=True,
    )
    print(
        f"  training={transform['training_matches']} "
        f"holdout={transform['holdout_matches']} "
        f"train_rmse={transform['train_rmse']:.6f} "
        f"holdout_rmse={_format_optional_float(transform['holdout_rmse'])}",
        flush=True,
    )
    print(
        f"  final_rmse={transform['rmse']:.6f} "
        f"max_error={transform['max_error']:.6f} "
        f"usable={transform['usable']}",
        flush=True,
    )
    print(
        f"  scale=({transform['scale_x']:.12g}, {transform['scale_y']:.12g}) "
        f"offset=({transform['offset_x']:.6f}, {transform['offset_y']:.6f})",
        flush=True,
    )
    if fitted["matches"]:
        worst = fitted["matches"][0]
        print(
            f"  worst_validation={worst['pearpal']['name']} "
            f"role={worst['fit_role']} error={worst['error_distance']:.6f}",
            flush=True,
        )
    _print_unmatched_checkpoint_fit(matching)
    for warning in transform["warnings"]:
        print(f"  warning: {warning}", flush=True)
    print(f"Transform written: {transform_output}", flush=True)
    print(f"Match report written: {matched_output}", flush=True)
    return 0


def _export_local_points(args: argparse.Namespace) -> int:
    client = _client(args)
    transform = load_transform(args.transform)
    target_coordinate = str(transform.get("target_coordinate") or "")
    if target_coordinate and target_coordinate != WHIMBOX_PNG_TARGET:
        raise PearPalDebugError(
            "transform target_coordinate is not Whimbox full-resolution PNG: "
            f"{target_coordinate}"
        )
    if not target_coordinate:
        print(
            "warning: legacy transform does not declare target_coordinate; "
            "verify that image_x/image_y are full-resolution PNG coordinates",
            flush=True,
        )
    prepared = _prepare_catalog_fetch(
        client,
        world_id=args.world_id,
        catalog_id=args.catalog_id,
        language=args.language,
        limit=args.limit,
        name_contains=None,
    )
    summary = prepared["summary"]
    if summary["catalog_filter_status"] == "unresolved":
        raise PearPalDebugError(
            "catalog_filter_unresolved: refusing local-point export because the "
            "public spawner response is not catalog-clean"
        )
    candidates = prepared["limited_normalized"]
    map_name = args.map_name or str(transform.get("map_name") or "miraland")
    points: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate["is_candidate_visible"]:
            continue
        image_x, image_y = apply_pearpal_transform(
            float(candidate["web_x"]),
            float(candidate["web_y"]),
            transform,
        )
        points.append(
            {
                "id": (
                    f"pearpal_{_id_component(args.world_id)}_"
                    f"{_id_component(candidate['source_id'])}"
                ),
                "label_id": f"pearpal_{_id_component(args.catalog_id)}",
                "name": candidate["name"],
                "map_name": map_name,
                "image_x": image_x,
                "image_y": image_y,
                "icon": candidate["icon"],
                "provider": "pearpal-debug",
                "detail": {
                    "description": candidate["description"],
                    "source_id": candidate["source_id"],
                    "world_id": candidate["world_id"],
                    "catalog_id": candidate["catalog_id"],
                    "stage_id": candidate["stage_id"],
                    "raw_tags": candidate["raw_tags"],
                    "normalization_warning": candidate["normalization_warning"],
                },
            }
        )
    output_path = Path(args.output) if args.output else _default_local_export_path()
    output = write_json(output_path, points)
    print(
        f"Exported {len(points)} debug points from world={args.world_id} "
        f"catalog={args.catalog_id}",
        flush=True,
    )
    print(f"LocalJsonProvider validation file: {output}", flush=True)
    print(
        "This file is a manual debug export; OfficialPearPalProvider remains disabled.",
        flush=True,
    )
    return 0


def _prepare_catalog_fetch(
    client: PearPalPublicDebugClient,
    *,
    world_id: str,
    catalog_id: str,
    language: str,
    limit: int,
    name_contains: str | None,
) -> dict[str, Any]:
    requested_world_id = str(world_id)
    requested_catalog_id = str(catalog_id)
    catalog_response, catalog_fetch = client.fetch_catalog(requested_world_id)
    catalog = find_catalog(catalog_response, requested_catalog_id, language)
    if catalog is None:
        raise PearPalDebugError(
            f"catalog {requested_catalog_id} was not found in world {requested_world_id}"
        )
    raw_points, spawner_fetch = client.fetch_spawners(requested_world_id)
    stages, stage_fetch = client.fetch_stage_spawners()

    world_filtered = [
        item
        for item in raw_points
        if spawner_world_id(item) == requested_world_id
    ]
    catalog_values = [spawner_catalog_id(item) for item in world_filtered]
    direct_catalog_resolved = bool(world_filtered) and all(
        value is not None for value in catalog_values
    )
    direct_filtered = [
        item
        for item in world_filtered
        if spawner_catalog_id(item) == requested_catalog_id
    ]
    expanded, stage_info = expand_stage_spawners(world_filtered, stages)
    stage_filtered = [
        item
        for item in expanded
        if spawner_catalog_id(item) == requested_catalog_id
    ]

    warnings: list[str] = []
    if direct_catalog_resolved:
        catalog_filter_status = (
            "resolved_stage_tag"
            if not direct_filtered and stage_filtered
            else "resolved_direct_field"
        )
        selected_raw = stage_filtered
        preview_mode = "filtered candidates"
    else:
        catalog_filter_status = "unresolved"
        selected_raw = world_filtered
        preview_mode = "unfiltered debug candidates"
        warnings.extend(
            [
                "catalog_filter_unresolved",
                "spawner/list raw is not catalog-clean; provider not safe yet",
            ]
        )

    search_text = (name_contains or "").strip()
    if search_text:
        folded = search_text.casefold()
        selected_raw = [
            item
            for item in selected_raw
            if folded in raw_spawner_name(item, language).casefold()
        ]

    normalized: list[dict[str, Any]] = []
    candidate_count = 0
    item_warning_count = 0
    for raw in selected_raw:
        item = normalize_spawner(
            raw,
            requested_world_id=requested_world_id,
            requested_catalog_id=requested_catalog_id,
            catalog=catalog,
            language=language,
            catalog_filter_resolved=catalog_filter_status != "unresolved",
        )
        if item["is_candidate_visible"]:
            candidate_count += 1
        if item["normalization_warning"]:
            item_warning_count += 1
        if len(normalized) < limit:
            normalized.append(item)

    declared_count = catalog.get("count")
    try:
        declared_count = int(declared_count)
    except (TypeError, ValueError):
        declared_count = None
    if (
        catalog_filter_status != "unresolved"
        and declared_count is not None
        and len(stage_filtered) != declared_count
    ):
        warnings.append(
            "filtered count differs from catalog declared count; stage/tag/layer "
            "semantics may still need validation"
        )

    summary = {
        "requested_world_id": requested_world_id,
        "requested_catalog_id": requested_catalog_id,
        "catalog_name": str(catalog.get("_localized_name") or ""),
        "catalog_declared_count": declared_count,
        "raw_total": len(raw_points),
        "after_world_filter": len(world_filtered),
        "after_catalog_filter": len(direct_filtered),
        "after_stage_filter": len(stage_filtered),
        "normalized_candidates": (
            candidate_count if catalog_filter_status != "unresolved" else 0
        ),
        "unfiltered_debug_candidates": (
            len(selected_raw) if catalog_filter_status == "unresolved" else 0
        ),
        "warnings_count": len(warnings) + item_warning_count,
        "warnings": warnings,
        "catalog_filter_status": catalog_filter_status,
        "preview_mode": preview_mode,
        "name_contains": search_text,
        "name_filter_matches": len(selected_raw) if search_text else None,
        "catalog_field_names": _present_field_names(
            world_filtered,
            ("catalog_id", "catalogId", "catalog", "category", "catalog_ids"),
        ),
        "world_field_names": _present_field_names(
            raw_points,
            ("world_id", "worldId"),
        ),
        "distinct_catalog_values": len(
            {value for value in catalog_values if value is not None}
        ),
        "stage_relation": stage_info,
        "catalog_cache_hit": catalog_fetch.cache_hit,
        "spawner_cache_hit": spawner_fetch.cache_hit,
        "stage_cache_hit": stage_fetch.cache_hit,
        "cache_path": str(spawner_fetch.cache_path or ""),
        "safety_notice": (
            "spawner/list raw is not catalog-clean; provider not safe yet"
            if catalog_filter_status == "unresolved"
            else "catalog filtering resolved for this debug response; formal provider remains disabled"
        ),
    }
    return {
        "summary": summary,
        "world_filtered_raw": world_filtered,
        "limited_raw": selected_raw[:limit],
        "limited_normalized": normalized,
    }


def _world_summary(world: dict[str, Any], language: str) -> dict[str, Any]:
    return {
        "world_id": str(world.get("id") or world.get("world_id") or ""),
        "name": localized_text(world.get("map_name"), language),
        "map_size": world.get("map_size"),
        "map_resource_url": world.get("map_resource_url"),
        "zoom_range": world.get("zoom_range"),
        "parent_world_id": world.get("parent_world_id"),
        "world_type": world.get("world_type"),
        "layers": summarize_layers(world, language),
    }


def _catalog_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_id": str(catalog.get("id") or ""),
        "name": str(catalog.get("_localized_name") or ""),
        "group_id": str(catalog.get("_group_id") or ""),
        "group_name": str(catalog.get("_group_name") or ""),
        "count": catalog.get("count"),
        "icon": str(catalog.get("_icon") or ""),
        "can_marking": catalog.get("can_marking"),
    }


def _find_world(worlds: list[Any], world_id: str) -> dict[str, Any]:
    target = str(world_id)
    for item in worlds:
        if isinstance(item, dict) and str(
            item.get("id") or item.get("world_id") or ""
        ) == target:
            return item
    raise PearPalDebugError(f"world {world_id} was not found in public config")


def _print_discovery(report: dict[str, Any]) -> None:
    print(
        f"PearPal public discovery: region={report['region']} anonymous=true "
        f"cache={report['cache_dir']}",
        flush=True,
    )
    print(
        f"Worlds: {report['world_count']} "
        f"(cache_hit={report['world_cache_hit']})",
        flush=True,
    )
    for item in report["worlds"]:
        print(
            f"  world={item['world_id']} name={item['name']} size={item['map_size']} "
            f"resource={item['map_resource_url']} zoom={item['zoom_range']} "
            f"layers={item['layers']['count']}",
            flush=True,
        )
        for layer in item["layers"]["items"]:
            print(
                f"    layer={layer['id']} name={layer['name']} "
                f"bounds={layer['left_top']}..{layer['right_bottom']}",
                flush=True,
            )
    print(
        f"Catalogs: {report['catalog_count']} "
        f"(cache_hit={report['catalog_cache_hit']})",
        flush=True,
    )
    for item in report["catalogs"]:
        print(
            f"  catalog={item['catalog_id']} name={item['name']} count={item['count']} "
            f"group={item['group_name']} icon={item['icon']}",
            flush=True,
        )
    tile = report["tile"]
    print(
        f"Single tile: status={tile.get('status')} size="
        f"{tile.get('width')}x{tile.get('height')} bytes={tile.get('bytes')} "
        f"url={tile.get('url', '')}",
        flush=True,
    )


def _print_fetch_summary(
    report: dict[str, Any],
    preview: list[dict[str, Any]],
) -> None:
    print(
        "PearPal public spawner fetch: "
        f"world={report['requested_world_id']} "
        f"catalog={report['requested_catalog_id']} "
        f"name={report['catalog_name']}",
        flush=True,
    )
    print(
        f"  requested_world_id={report['requested_world_id']} "
        f"requested_catalog_id={report['requested_catalog_id']} "
        f"catalog_declared_count={report['catalog_declared_count']}",
        flush=True,
    )
    print(
        f"  raw_total={report['raw_total']} "
        f"after_world_filter={report['after_world_filter']} "
        f"after_catalog_filter={report['after_catalog_filter']} "
        f"after_stage_filter={report['after_stage_filter']}",
        flush=True,
    )
    print(
        f"  normalized_candidates={report['normalized_candidates']} "
        f"unfiltered_debug_candidates={report['unfiltered_debug_candidates']} "
        f"warnings_count={report['warnings_count']}",
        flush=True,
    )
    print(
        f"  catalog_filter_status={report['catalog_filter_status']} "
        f"catalog_fields={','.join(report['catalog_field_names']) or 'none'} "
        f"distinct_catalog_values={report['distinct_catalog_values']}",
        flush=True,
    )
    stage = report["stage_relation"]
    print(
        f"  stage_relation={stage['stage_relation_status']} "
        f"stages={stage['stage_count']} "
        f"matched_parents={stage['matched_stage_parent_count']} "
        f"expanded_children={stage['expanded_stage_child_count']}",
        flush=True,
    )
    print(
        f"  cache_hit={report['spawner_cache_hit']} "
        f"cache_path={report['cache_path']}",
        flush=True,
    )
    if report["name_contains"]:
        print(
            f"  name_contains={report['name_contains']!r} "
            f"matches={report['name_filter_matches']}",
            flush=True,
        )
    for warning in report["warnings"]:
        print(f"  warning: {warning}", flush=True)
    print(
        f"  Preview: {report['preview_mode']} ({len(preview)}):",
        flush=True,
    )
    for item in preview:
        print(
            f"    id={item['source_id']} name={item['name']} "
            f"web=({item['web_x']}, {item['web_y']}) stage={item['stage_id']} "
            f"candidate={item['is_candidate_visible']} "
            f"warning={item['normalization_warning'] or '-'}",
            flush=True,
        )


def _present_field_names(
    rows: list[dict[str, Any]],
    field_names: tuple[str, ...],
) -> list[str]:
    return [
        field
        for field in field_names
        if any(field in row for row in rows)
    ]


def _raw_field_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    key_patterns = Counter(tuple(sorted(row)) for row in rows)
    catalog_values = Counter(
        str(value)
        for row in rows
        if (value := spawner_catalog_id(row)) is not None
    )
    world_values = Counter(
        str(value)
        for row in rows
        if (value := spawner_world_id(row)) is not None
    )
    return {
        "rows_inspected": len(rows),
        "key_patterns": [
            {"keys": list(keys), "count": count}
            for keys, count in key_patterns.most_common(20)
        ],
        "catalog_field_names": _present_field_names(
            rows,
            ("catalog_id", "catalogId", "catalog", "category", "catalog_ids"),
        ),
        "catalog_value_counts": [
            {"value": value, "count": count}
            for value, count in catalog_values.most_common(100)
        ],
        "world_field_names": _present_field_names(
            rows,
            ("world_id", "worldId"),
        ),
        "world_value_counts": [
            {"value": value, "count": count}
            for value, count in world_values.most_common(20)
        ],
    }


def _print_field_inspection(summary: dict[str, Any]) -> None:
    print(
        f"  Raw field inspection: rows={summary['rows_inspected']} "
        f"catalog_fields={','.join(summary['catalog_field_names']) or 'none'} "
        f"world_fields={','.join(summary['world_field_names']) or 'none'}",
        flush=True,
    )
    for pattern in summary["key_patterns"][:5]:
        print(
            f"    keys[{pattern['count']}]={','.join(pattern['keys'])}",
            flush=True,
        )
    catalog_counts = ", ".join(
        f"{item['value']}:{item['count']}"
        for item in summary["catalog_value_counts"][:20]
    )
    print(f"    catalog_values={catalog_counts or 'none'}", flush=True)


def _print_unmatched_checkpoint_fit(matching: dict[str, Any]) -> None:
    pearpal_names = [
        str(item.get("name") or "")
        for item in matching["unmatched_pearpal"]
    ]
    checkpoint_names = [
        str(item.get("name") or "")
        for item in matching["unmatched_checkpoints"]
    ]
    ambiguous_names = [
        str(item.get("normalized_name") or "")
        for item in matching["ambiguous_matches"]
    ]
    print(
        f"  unmatched PearPal: {', '.join(pearpal_names) or 'none'}",
        flush=True,
    )
    print(
        f"  unmatched checkpoints: {', '.join(checkpoint_names) or 'none'}",
        flush=True,
    )
    print(
        f"  ambiguous: {', '.join(ambiguous_names) or 'none'}",
        flush=True,
    )


def _bounded_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _holdout_ratio(value: str) -> float:
    try:
        ratio = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("holdout ratio must be numeric") from exc
    if not 0 <= ratio < 1:
        raise argparse.ArgumentTypeError("holdout ratio must be in the range [0, 1)")
    return ratio


def _minimum_matches(value: str) -> int:
    try:
        minimum = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("min matches must be an integer") from exc
    if minimum < 2:
        raise argparse.ArgumentTypeError("min matches must be at least 2")
    return minimum


def _resolve_flip_origin(
    explicit_value: float | None,
    metadata: dict[str, Any],
    metadata_key: str,
    landmarks: list[dict[str, Any]],
    coordinate_key: str,
) -> float:
    raw_value: Any = explicit_value
    if raw_value is None:
        raw_value = metadata.get(metadata_key, metadata.get("web_map_size"))
    if raw_value is None:
        raw_value = max(float(item[coordinate_key]) for item in landmarks)
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise PearPalDebugError(
            f"{metadata_key}/web_map_size must be numeric"
        ) from exc
    if not math.isfinite(value):
        raise PearPalDebugError(f"{metadata_key} must be finite")
    return value


def _format_optional_float(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:.4f}" if math.isfinite(number) else "n/a"


def _default_local_export_path() -> Path:
    whimbox_root = Path(__file__).resolve().parents[3]
    return whimbox_root / "assets" / "map_mask" / "points.pearpal.local.json"


def _id_component(value: Any) -> str:
    text = "".join(character if character.isalnum() else "_" for character in str(value))
    return text.strip("_") or "unknown"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
