from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "fit-center-correction":
        return _fit_center_correction(arguments[1:])

    parser = argparse.ArgumentParser(description="Continuously print map-mask auto viewport state.")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between polls")
    parser.add_argument(
        "--mode",
        default=os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_MODE") or "hybrid-auto-center",
        choices=("sample", "manual-calibration", "auto-placeholder", "hybrid-auto-center"),
        help="viewport mode to use",
    )
    parser.add_argument(
        "--bigmap-mode",
        default=os.environ.get("WHIMBOX_MAP_MASK_BIGMAP_DETECTION_MODE") or "",
        choices=("", "auto", "force-open", "force-closed"),
        help="optional bigmap detection mode override",
    )
    parser.add_argument("--verbose", action="store_true", help="print visible point details")
    parser.add_argument(
        "--point-name",
        default="",
        help="print the loaded point's PNG and projected screen coordinates",
    )
    parser.add_argument(
        "--reject-far-from-point",
        action="store_true",
        help="reject global matches farther than the expected-point distance gate",
    )
    parser.add_argument(
        "--save-capture",
        action="store_true",
        help="save one raw client capture and map-area crop",
    )
    parser.add_argument(
        "--save-match-debug",
        action="store_true",
        help="save one BigMap preprocessing/top5/heatmap diagnostic bundle",
    )
    parser.add_argument(
        "--debug-output-dir",
        default="debug_bigmap_match",
        help="directory for --save-capture and --save-match-debug",
    )
    parser.add_argument(
        "--save-log",
        action="store_true",
        help="save per-frame JSONL and CSV logs",
    )
    parser.add_argument(
        "--save-screenshot-every",
        type=int,
        default=0,
        metavar="N",
        help="save the current client capture every N frames (0 disables)",
    )
    parser.add_argument(
        "--artifact-dir",
        default="map-mask-auto-viewport-artifacts",
        help="directory for logs and screenshots",
    )
    args = parser.parse_args(arguments)

    os.environ["WHIMBOX_MAP_MASK_VIEWPORT_MODE"] = args.mode

    from .service import map_mask_service

    known_point = _resolve_known_point(map_mask_service, args.point_name)
    if known_point is not None:
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_X"] = str(
            known_point.image_x
        )
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_Y"] = str(
            known_point.image_y
        )
        if args.reject_far_from_point:
            os.environ[
                "WHIMBOX_MAP_MASK_VIEWPORT_REJECT_FAR_EXPECTED_CENTER"
            ] = "1"

    if args.bigmap_mode:
        map_mask_service.set_bigmap_detection_mode(args.bigmap_mode)

    print(
        "Running map mask auto viewport debug "
        f"for {args.duration:.1f}s, poll={args.interval:.2f}s, mode={args.mode}",
        flush=True,
    )

    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    run_timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    records: list[dict[str, Any]] = []
    screenshots: list[dict[str, Any]] = []
    match_debug_saved = False
    if args.save_log or args.save_screenshot_every > 0:
        artifact_dir.mkdir(parents=True, exist_ok=True)

    end_time = time.monotonic() + max(0.0, args.duration)
    frame_index = 0
    while time.monotonic() < end_time:
        frame_index += 1
        started = time.perf_counter()
        result = map_mask_service.get_visible_points()
        state = result.get("state") if isinstance(result, dict) else {}
        if not isinstance(state, dict):
            state = {}
        viewport = result.get("viewport") if isinstance(result, dict) else {}
        if not isinstance(viewport, dict) or not viewport:
            viewport = state.get("viewport") if isinstance(state.get("viewport"), dict) else {}
        points = result.get("points") if isinstance(result, dict) else []
        if not isinstance(points, list):
            points = []

        elapsed_ms = (time.perf_counter() - started) * 1000
        timestamp = datetime.now(tz=UTC).isoformat()
        record = _build_frame_record(
            frame_index=frame_index,
            timestamp=timestamp,
            state=state,
            viewport=viewport,
            points=points,
            elapsed_ms=elapsed_ms,
        )
        records.append(record)
        print(_format_state_line(state, viewport, points, elapsed_ms, timestamp), flush=True)
        if args.point_name:
            print(
                _format_known_point(
                    map_mask_service,
                    args.point_name,
                    viewport,
                ),
                flush=True,
            )
        if args.verbose:
            print(_format_visible_points(points), flush=True)

        if (
            not match_debug_saved
            and bool(state.get("is_bigmap_open"))
            and (args.save_capture or args.save_match_debug)
        ):
            debug_result = _save_bigmap_match_debug(
                service=map_mask_service,
                state=state,
                viewport=viewport,
                output_dir=Path(args.debug_output_dir).expanduser().resolve(),
                run_timestamp=run_timestamp,
                save_capture=args.save_capture,
                save_match_debug=args.save_match_debug,
                known_point=known_point,
            )
            print(
                f"  match_debug={json.dumps(debug_result, ensure_ascii=False)}",
                flush=True,
            )
            match_debug_saved = debug_result.get("status") == "saved"

        if args.save_screenshot_every > 0 and frame_index % args.save_screenshot_every == 0:
            screenshot_path = artifact_dir / (
                f"capture-{run_timestamp}-frame-{frame_index:04d}.png"
            )
            screenshot_result = _save_current_capture(screenshot_path)
            screenshots.append(
                {
                    "frame": frame_index,
                    "timestamp": timestamp,
                    **screenshot_result,
                }
            )
            print(
                f"  screenshot={json.dumps(screenshot_result, ensure_ascii=False)}",
                flush=True,
            )

        sleep_time = args.interval - (time.perf_counter() - started)
        if sleep_time > 0:
            time.sleep(sleep_time)

    summary = _build_summary(records)
    print(f"Summary: {json.dumps(summary, ensure_ascii=False)}", flush=True)

    if args.save_log:
        jsonl_path = artifact_dir / f"auto-viewport-{run_timestamp}.jsonl"
        csv_path = artifact_dir / f"auto-viewport-{run_timestamp}.csv"
        _write_jsonl(jsonl_path, records)
        _write_csv(csv_path, records)
        summary_path = artifact_dir / f"auto-viewport-{run_timestamp}-summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "screenshots": screenshots,
                    "environment": _stability_environment(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"JSONL log: {jsonl_path}", flush=True)
        print(f"CSV log: {csv_path}", flush=True)
        print(f"Summary report: {summary_path}", flush=True)

    return 0


def _fit_center_correction(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="debug_auto_viewport.py fit-center-correction",
        description="Fit accepted BigMap centers to expected Whimbox PNG centers.",
    )
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", default="center_correction.json")
    parser.add_argument("--source", default="fitted/debug")
    args = parser.parse_args(argv)

    source = Path(args.observations).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        parser.error(
            f"failed to read observations {source}: {type(exc).__name__}: {exc}"
        )
    observations = (
        payload.get("observations")
        if isinstance(payload, dict)
        else payload
    )
    if not isinstance(observations, list) or not observations:
        parser.error("observations JSON must be a non-empty list")
    normalized = [
        _normalize_center_observation(item, index)
        for index, item in enumerate(observations)
    ]

    if len(normalized) >= 4:
        scale_x, offset_x = _fit_center_axis(
            [item["accepted_center_x"] for item in normalized],
            [item["expected_png_x"] for item in normalized],
            axis="x",
        )
        scale_y, offset_y = _fit_center_axis(
            [item["accepted_center_y"] for item in normalized],
            [item["expected_png_y"] for item in normalized],
            axis="y",
        )
        fit_mode = "scale-and-offset"
        warning = ""
    else:
        scale_x = 1.0
        scale_y = 1.0
        offset_x = sum(
            item["expected_png_x"] - item["accepted_center_x"]
            for item in normalized
        ) / len(normalized)
        offset_y = sum(
            item["expected_png_y"] - item["accepted_center_y"]
            for item in normalized
        ) / len(normalized)
        fit_mode = "single-point-offset" if len(normalized) == 1 else "mean-offset"
        warning = (
            ""
            if len(normalized) == 1
            else "fewer than four observations; scale remains fixed at 1.0"
        )

    errors = []
    squared_error_sum = 0.0
    max_error = 0.0
    for item in normalized:
        predicted_x = scale_x * item["accepted_center_x"] + offset_x
        predicted_y = scale_y * item["accepted_center_y"] + offset_y
        error_x = predicted_x - item["expected_png_x"]
        error_y = predicted_y - item["expected_png_y"]
        error_distance = math.hypot(error_x, error_y)
        squared_error_sum += error_distance * error_distance
        max_error = max(max_error, error_distance)
        errors.append(
            {
                **item,
                "predicted_png_x": predicted_x,
                "predicted_png_y": predicted_y,
                "error_x": error_x,
                "error_y": error_y,
                "error_distance": error_distance,
            }
        )
    rmse = math.sqrt(squared_error_sum / len(normalized))
    result = {
        "version": 1,
        "source_observations": str(source),
        "observation_count": len(normalized),
        "fit_mode": fit_mode,
        "center_correction": {
            "enabled": True,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "source": args.source,
        },
        "rmse": rmse,
        "max_error": max_error,
        "warning": warning,
        "observations": errors,
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Center correction fit: observations={len(normalized)} "
        f"mode={fit_mode} rmse={rmse:.6f} max_error={max_error:.6f}",
        flush=True,
    )
    print(
        f"  scale=({scale_x:.12g}, {scale_y:.12g}) "
        f"offset=({offset_x:.6f}, {offset_y:.6f})",
        flush=True,
    )
    if warning:
        print(f"  warning: {warning}", flush=True)
    for item in errors:
        print(
            f"  {item['name']}: error={item['error_distance']:.6f} "
            f"delta=({item['error_x']:.6f}, {item['error_y']:.6f})",
            flush=True,
        )
    print(f"Center correction written: {output}", flush=True)
    return 0


def _normalize_center_observation(
    item: Any,
    index: int,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SystemExit(f"observation {index} must be an object")
    normalized: dict[str, Any] = {
        "name": str(item.get("name") or f"observation_{index + 1}"),
        "confidence": item.get("confidence"),
        "accept_reason": str(item.get("accept_reason") or ""),
    }
    for key in (
        "expected_png_x",
        "expected_png_y",
        "accepted_center_x",
        "accepted_center_y",
    ):
        try:
            value = float(item[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"observation {index} has invalid {key}") from exc
        if not math.isfinite(value):
            raise SystemExit(f"observation {index} has non-finite {key}")
        normalized[key] = value
    return normalized


def _fit_center_axis(
    source: list[float],
    target: list[float],
    *,
    axis: str,
) -> tuple[float, float]:
    source_mean = sum(source) / len(source)
    target_mean = sum(target) / len(target)
    denominator = sum((value - source_mean) ** 2 for value in source)
    if denominator <= 1e-12:
        raise SystemExit(
            f"accepted center {axis} values need variation to fit scale"
        )
    scale = sum(
        (source_value - source_mean) * (target_value - target_mean)
        for source_value, target_value in zip(source, target)
    ) / denominator
    return scale, target_mean - scale * source_mean


def _format_state_line(
    state: dict[str, Any],
    viewport: dict[str, Any],
    points: list[Any],
    elapsed_ms: float,
    timestamp: str,
) -> str:
    return (
        f"{timestamp} "
        f"bigmap={_bool_word(state.get('is_bigmap_open'))} "
        f"raw={_bool_word(state.get('raw_is_bigmap_open'))} "
        f"open={_bool_word(state.get('is_bigmap_open'))} "
        f"capture={_capture_status(state)} "
        f"mode={state.get('viewport_mode') or 'n/a'} "
        f"source={state.get('viewport_source') or 'n/a'} "
        f"raw_center=({_num(state.get('raw_center_x'))},{_num(state.get('raw_center_y'))}) "
        f"accepted_center=({_num(state.get('accepted_center_x'))},"
        f"{_num(state.get('accepted_center_y'))}) "
        f"corrected_center=({_num(state.get('corrected_center_x'))},"
        f"{_num(state.get('corrected_center_y'))}) "
        f"correction_source={state.get('center_correction_source') or 'disabled'} "
        f"correction_enabled={_bool_word(state.get('center_correction_enabled'))} "
        f"map_scale={_num(state.get('map_scale'), digits=4)} "
        f"span_source={state.get('viewport_span_source') or 'n/a'} "
        f"assumes_max_zoom={_bool_word(state.get('assumes_max_bigmap_zoom'))} "
        f"pending_center=({_num(state.get('pending_center_x'))},"
        f"{_num(state.get('pending_center_y'))}) "
        f"jump={_num(state.get('center_jump_distance'))} "
        f"accept={(state.get('center_accept_reason') or '')!r} "
        f"reject={(state.get('center_rejected_reason') or '')!r} "
        f"pending_count={int(state.get('pending_confirm_count') or 0)} "
        f"last_good_age_ms={_num(state.get('last_good_center_age_ms'))} "
        f"smoothing_mode={state.get('smoothing_mode') or 'off'} "
        f"smoothing_applied={_bool_word(state.get('smoothing_applied'))} "
        f"smoothing_distance={_num(state.get('smoothing_distance'))} "
        f"snap_reason={(state.get('snap_reason') or '')!r} "
        f"tracking={state.get('tracking_mode') or 'idle'} "
        f"motion_diff={_num(state.get('motion_diff'), digits=2)} "
        f"motion_unstable={_bool_word(state.get('motion_unstable'))} "
        f"candidate_distance={_num(state.get('candidate_distance_to_last_good'))} "
        f"local_confidence={_num(state.get('local_match_confidence'), digits=3)} "
        f"global_confidence={_num(state.get('global_match_confidence'), digits=3)} "
        f"match_source={state.get('selected_match_source') or 'none'} "
        f"reacquire_count={int(state.get('reacquire_pending_count') or 0)} "
        f"tracking_center=({_num(state.get('tracking_center_x'))},"
        f"{_num(state.get('tracking_center_y'))}) "
        f"global_check_center=({_num(state.get('global_check_center_x'))},"
        f"{_num(state.get('global_check_center_y'))}) "
        f"global_check_delta={_num(state.get('global_check_delta'))} "
        f"global_check_confidence={_num(state.get('global_check_confidence'), digits=3)} "
        f"tracking_suspect={_bool_word(state.get('tracking_suspect'))} "
        f"tracking_reset={(state.get('tracking_reset_reason') or '')!r} "
        f"matching_status={state.get('matching_status') or 'matching_failed'} "
        f"matching_reject={(state.get('matching_rejection_reason') or '')!r} "
        f"raw_top1={_num(state.get('global_match_top1_confidence'), digits=3)} "
        f"raw_top2={_num(state.get('global_match_top2_confidence'), digits=3)} "
        f"margin={_num(state.get('global_match_margin'), digits=3)} "
        f"selected_confidence={_num(state.get('global_selected_confidence'), digits=3)} "
        f"selected_top1_delta={_num(state.get('global_selected_to_top1_distance'))} "
        f"image=({_num(viewport.get('image_left'))},{_num(viewport.get('image_top'))},"
        f"{_num(viewport.get('image_width'))},{_num(viewport.get('image_height'))}) "
        f"nearest_point={(state.get('nearest_loaded_point_name') or 'none')!r} "
        f"nearest_image=({_num(state.get('nearest_loaded_point_image_x'))},"
        f"{_num(state.get('nearest_loaded_point_image_y'))}) "
        f"nearest_delta_image=({_num(state.get('nearest_loaded_point_delta_image_x'))},"
        f"{_num(state.get('nearest_loaded_point_delta_image_y'))}) "
        f"nearest_delta_screen=({_num(state.get('nearest_loaded_point_delta_screen_x'))},"
        f"{_num(state.get('nearest_loaded_point_delta_screen_y'))}) "
        f"nearest_label={state.get('nearest_loaded_point_label_id') or 'none'} "
        f"label_exists={_bool_word(state.get('nearest_loaded_point_label_exists'))} "
        f"label_enabled={_bool_word(state.get('nearest_loaded_point_label_enabled'))} "
        f"final_visible={_bool_word(state.get('nearest_loaded_point_final_visible'))} "
        f"invisible_reason={(state.get('nearest_loaded_point_invisible_reason') or '')!r} "
        f"confidence={_num(state.get('viewport_detection_confidence'), digits=3)} "
        f"fallback={_bool_word(state.get('viewport_fallback_used'))} "
        f"stale={_bool_word(state.get('viewport_stale'))} "
        f"fallback_reason={(state.get('viewport_fallback_reason') or '')!r} "
        f"error={(state.get('viewport_detection_error') or '')!r} "
        f"visible_points={len(points)} "
        f"duration_ms={elapsed_ms:.1f}"
    )


def _build_frame_record(
    *,
    frame_index: int,
    timestamp: str,
    state: dict[str, Any],
    viewport: dict[str, Any],
    points: list[Any],
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "frame": frame_index,
        "timestamp": timestamp,
        "bigmap_open": bool(state.get("is_bigmap_open")),
        "capture": _capture_status(state),
        "viewport_mode": state.get("viewport_mode") or "",
        "viewport_source": state.get("viewport_source") or "",
        "raw_center_x": state.get("raw_center_x"),
        "raw_center_y": state.get("raw_center_y"),
        "accepted_center_x": state.get("accepted_center_x"),
        "accepted_center_y": state.get("accepted_center_y"),
        "corrected_center_x": state.get("corrected_center_x"),
        "corrected_center_y": state.get("corrected_center_y"),
        "center_correction_enabled": bool(
            state.get("center_correction_enabled")
        ),
        "center_correction_source": state.get("center_correction_source") or "",
        "pending_center_x": state.get("pending_center_x"),
        "pending_center_y": state.get("pending_center_y"),
        "center_jump_distance": state.get("center_jump_distance"),
        "center_accept_reason": state.get("center_accept_reason") or "",
        "center_rejected_reason": state.get("center_rejected_reason") or "",
        "pending_confirm_count": int(state.get("pending_confirm_count") or 0),
        "last_good_center_age_ms": state.get("last_good_center_age_ms"),
        "smoothing_mode": state.get("smoothing_mode") or "off",
        "smoothing_applied": bool(state.get("smoothing_applied")),
        "smoothing_distance": state.get("smoothing_distance"),
        "snap_reason": state.get("snap_reason") or "",
        "tracking_mode": state.get("tracking_mode") or "idle",
        "motion_diff": state.get("motion_diff"),
        "motion_unstable": bool(state.get("motion_unstable")),
        "candidate_distance_to_last_good": state.get(
            "candidate_distance_to_last_good"
        ),
        "local_match_confidence": state.get("local_match_confidence"),
        "global_match_confidence": state.get("global_match_confidence"),
        "selected_match_source": state.get("selected_match_source") or "none",
        "reacquire_pending_count": int(state.get("reacquire_pending_count") or 0),
        "tracking_center_x": state.get("tracking_center_x"),
        "tracking_center_y": state.get("tracking_center_y"),
        "global_check_center_x": state.get("global_check_center_x"),
        "global_check_center_y": state.get("global_check_center_y"),
        "global_check_delta": state.get("global_check_delta"),
        "global_check_confidence": state.get("global_check_confidence"),
        "tracking_suspect": bool(state.get("tracking_suspect")),
        "tracking_reset_reason": state.get("tracking_reset_reason") or "",
        "last_global_check_time": state.get("last_global_check_time") or "",
        "matching_status": state.get("matching_status") or "matching_failed",
        "matching_rejection_reason": (
            state.get("matching_rejection_reason") or ""
        ),
        "global_match_top1_confidence": state.get(
            "global_match_top1_confidence"
        ),
        "global_match_top2_confidence": state.get(
            "global_match_top2_confidence"
        ),
        "global_match_margin": state.get("global_match_margin"),
        "global_selected_confidence": state.get("global_selected_confidence"),
        "global_selected_local_score": state.get(
            "global_selected_local_score"
        ),
        "global_selected_to_top1_distance": state.get(
            "global_selected_to_top1_distance"
        ),
        "map_scale": state.get("map_scale"),
        "map_scale_source": state.get("map_scale_source") or "",
        "viewport_span_source": state.get("viewport_span_source") or "",
        "assumes_max_bigmap_zoom": bool(state.get("assumes_max_bigmap_zoom")),
        "image_left": viewport.get("image_left"),
        "image_top": viewport.get("image_top"),
        "image_width": viewport.get("image_width"),
        "image_height": viewport.get("image_height"),
        "nearest_loaded_point_id": state.get("nearest_loaded_point_id") or "",
        "nearest_loaded_point_name": state.get("nearest_loaded_point_name") or "",
        "nearest_loaded_point_image_x": state.get(
            "nearest_loaded_point_image_x"
        ),
        "nearest_loaded_point_image_y": state.get(
            "nearest_loaded_point_image_y"
        ),
        "nearest_loaded_point_delta_image_x": state.get(
            "nearest_loaded_point_delta_image_x"
        ),
        "nearest_loaded_point_delta_image_y": state.get(
            "nearest_loaded_point_delta_image_y"
        ),
        "nearest_loaded_point_delta_screen_x": state.get(
            "nearest_loaded_point_delta_screen_x"
        ),
        "nearest_loaded_point_delta_screen_y": state.get(
            "nearest_loaded_point_delta_screen_y"
        ),
        "nearest_loaded_point_label_id": (
            state.get("nearest_loaded_point_label_id") or ""
        ),
        "nearest_loaded_point_label_exists": bool(
            state.get("nearest_loaded_point_label_exists")
        ),
        "nearest_loaded_point_label_enabled": bool(
            state.get("nearest_loaded_point_label_enabled")
        ),
        "nearest_loaded_point_final_visible": bool(
            state.get("nearest_loaded_point_final_visible")
        ),
        "nearest_loaded_point_invisible_reason": (
            state.get("nearest_loaded_point_invisible_reason") or ""
        ),
        "confidence": state.get("viewport_detection_confidence"),
        "fallback": bool(state.get("viewport_fallback_used")),
        "fallback_reason": state.get("viewport_fallback_reason") or "",
        "stale": bool(state.get("viewport_stale")),
        "visible_point_count": len(points),
        "duration_ms": round(elapsed_ms, 3),
    }


def _build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    confidences = [
        float(item["confidence"])
        for item in records
        if isinstance(item.get("confidence"), (int, float))
    ]
    jumps = [
        float(item["center_jump_distance"])
        for item in records
        if isinstance(item.get("center_jump_distance"), (int, float))
    ]
    frame_count = len(records)
    accepted_frames = sum(
        1 for item in records if bool(item.get("center_accept_reason"))
    )
    fallback_frames = sum(1 for item in records if bool(item.get("fallback")))
    return {
        "frames": frame_count,
        "accepted_frames": accepted_frames,
        "rejected_jump_frames": sum(
            1
            for item in records
            if (
                str(item.get("center_rejected_reason") or "").startswith("jump-")
                or "rejected-far-candidate-in-tracking"
                in str(item.get("center_rejected_reason") or "")
                or "rejected-top1-far-jump"
                in str(item.get("center_rejected_reason") or "")
            )
        ),
        "fallback_frames": fallback_frames,
        "smoothed_frames": sum(
            1 for item in records if bool(item.get("smoothing_applied"))
        ),
        "snapped_jump_frames": sum(
            1
            for item in records
            if str(item.get("center_accept_reason") or "")
            in {"confirmed-center-jump-snapped", "reacquire-pending-confirmed"}
            and not bool(item.get("smoothing_applied"))
        ),
        "tracking_frames": sum(
            1 for item in records if item.get("tracking_mode") == "tracking"
        ),
        "reacquire_frames": sum(
            1 for item in records if item.get("tracking_mode") == "reacquire"
        ),
        "motion_unstable_frames": sum(
            1 for item in records if bool(item.get("motion_unstable"))
        ),
        "far_candidate_rejected_frames": sum(
            1
            for item in records
            if "rejected-far-candidate-in-tracking"
            in str(item.get("center_rejected_reason") or "")
        ),
        "reacquire_confirmed_frames": sum(
            1
            for item in records
            if item.get("center_accept_reason") == "reacquire-pending-confirmed"
        ),
        "local_match_frames": sum(
            1 for item in records if item.get("selected_match_source") == "local"
        ),
        "global_match_frames": sum(
            1
            for item in records
            if item.get("selected_match_source")
            in {"global-top1", "local-match-failed-global-used"}
        ),
        "global_cross_check_resets": sum(
            1
            for item in records
            if item.get("center_accept_reason") == "global-cross-check-reset"
        ),
        "tracking_suspect_frames": sum(
            1 for item in records if bool(item.get("tracking_suspect"))
        ),
        "matching_ambiguous_frames": sum(
            1
            for item in records
            if item.get("matching_status") == "matching_ambiguous"
        ),
        "fallback_ratio": (
            round(fallback_frames / frame_count, 6) if frame_count else 0.0
        ),
        "accepted_ratio": (
            round(accepted_frames / frame_count, 6) if frame_count else 0.0
        ),
        "average_confidence": (
            round(sum(confidences) / len(confidences), 6) if confidences else None
        ),
        "max_jump_distance": round(max(jumps), 3) if jumps else None,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _save_current_capture(path: Path) -> dict[str, Any]:
    try:
        import cv2

        from whimbox.interaction.interaction_core import itt

        image = itt.capture()
        if image is None or not hasattr(image, "shape"):
            raise RuntimeError("capture returned no image")
        if not cv2.imwrite(str(path), image):
            raise RuntimeError("cv2.imwrite returned false")
        return {
            "status": "saved",
            "path": str(path),
            "shape": list(image.shape),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _resolve_known_point(service: Any, point_name: str) -> Any | None:
    if not point_name:
        return None
    try:
        matches = [
            point
            for point in service._list_points()
            if point.name == point_name
        ]
    except Exception as exc:  # noqa: BLE001
        print(
            f"Known point lookup failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None
    if not matches:
        print(f"Known point not loaded: {point_name}", flush=True)
        return None
    if len(matches) > 1:
        print(
            f"Known point is ambiguous ({len(matches)} matches): {point_name}",
            flush=True,
        )
        return None
    return matches[0]


def _save_bigmap_match_debug(
    *,
    service: Any,
    state: dict[str, Any],
    viewport: dict[str, Any],
    output_dir: Path,
    run_timestamp: str,
    save_capture: bool,
    save_match_debug: bool,
    known_point: Any | None,
) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np

        from whimbox.interaction.interaction_core import itt
        from whimbox.map.detection.bigmap import BigMap

        from .bigmap_match_diagnostics import analyze_bigmap_match

        image = itt.capture()
        if image is None or not hasattr(image, "shape"):
            raise RuntimeError("capture returned no image")
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"bigmap-match-{run_timestamp}"
        written: dict[str, str] = {}

        if save_capture or save_match_debug:
            capture_path = output_dir / f"{prefix}-capture.png"
            _write_debug_image(capture_path, image)
            written["capture"] = str(capture_path)

            map_crop = _crop_map_area(image, viewport)
            crop_path = output_dir / f"{prefix}-map-area.png"
            _write_debug_image(crop_path, map_crop)
            written["map_area"] = str(crop_path)

        if not save_match_debug:
            return {
                "status": "saved",
                "output_dir": str(output_dir),
                "files": written,
            }

        map_name = str(viewport.get("map_name") or "miraland")
        analysis = analyze_bigmap_match(image, map_name, top_k=5)
        original = BigMap()
        original.map_name = map_name
        original.update_bigmap(image)

        loaded_points = service._list_points(map_name=map_name)
        raw_candidates = _enrich_match_candidates(
            analysis.raw_candidates,
            loaded_points,
            known_point,
        )
        local_candidates = _enrich_match_candidates(
            analysis.local_candidates,
            loaded_points,
            known_point,
        )
        for candidate in local_candidates:
            print(
                "  local_candidate "
                f"rank={candidate['rank']} "
                f"center=({candidate['center_x']:.1f},{candidate['center_y']:.1f}) "
                f"confidence={candidate['confidence']:.3f} "
                f"local_score={candidate.get('local_score', 0.0):.4f} "
                f"nearest={candidate['nearest_loaded_point_name']!r} "
                f"distance={candidate['distance_to_nearest_point']:.1f} "
                f"near_known={candidate['near_known_point']}",
                flush=True,
            )
        for candidate in raw_candidates:
            print(
                "  raw_candidate "
                f"rank={candidate['rank']} "
                f"center=({candidate['center_x']:.1f},{candidate['center_y']:.1f}) "
                f"confidence={candidate['confidence']:.3f} "
                f"nearest={candidate['nearest_loaded_point_name']!r} "
                f"distance={candidate['distance_to_nearest_point']:.1f} "
                f"near_known={candidate['near_known_point']}",
                flush=True,
            )

        preprocessed_path = output_dir / f"{prefix}-preprocessed.png"
        _write_debug_image(preprocessed_path, analysis.preprocessed)
        written["preprocessed"] = str(preprocessed_path)

        annotated = _annotate_match_asset(
            analysis.asset,
            raw_candidates,
            local_candidates,
            analysis.selected_center,
        )
        annotated_path = output_dir / f"{prefix}-top5.png"
        _write_debug_image(annotated_path, annotated)
        written["top5"] = str(annotated_path)

        heatmap = cv2.normalize(
            analysis.result,
            None,
            0,
            255,
            cv2.NORM_MINMAX,
        ).astype(np.uint8)
        heatmap = cv2.applyColorMap(heatmap, cv2.COLORMAP_TURBO)
        heatmap_path = output_dir / f"{prefix}-heatmap.png"
        _write_debug_image(heatmap_path, heatmap)
        written["heatmap"] = str(heatmap_path)

        original_center = (
            float(original.bigmap_position[0]),
            float(original.bigmap_position[1]),
        )
        state_center = _pair_from_state(state, "raw_center_x", "raw_center_y")
        report = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "matching_status": state.get("matching_status"),
            "matching_rejection_reason": state.get("matching_rejection_reason"),
            "input_comparison": {
                "original_call": "BigMap.update_bigmap(capture)",
                "map_mask_diagnostic_call": "analyze_bigmap_match(capture)",
                "same_capture_object": True,
                "bigmap_input_scope": "full-client-capture",
                "map_area_crop_used_for_matching": False,
                "map_get_bigmap_posi_called": False,
                "map_get_bigmap_posi_note": (
                    "not called because it maximizes zoom and takes another capture"
                ),
                "preprocess": (
                    "rgb2luma -> resize(INTER_NEAREST, "
                    "BIGMAP_POSITION_SCALE_DICT[map] * BIGMAP_SEARCH_SCALE)"
                ),
                "asset": analysis.asset_name,
                "asset_path": analysis.asset_path,
                "asset_shape": list(analysis.asset_shape),
            },
            "original_bigmap": {
                "center": list(original_center),
                "reported_global_confidence": float(original.bigmap_similarity),
                "selected_local_score": float(original.bigmap_similarity_local),
            },
            "diagnostic_bigmap": analysis.to_report(),
            "original_vs_diagnostic_center_delta": math.hypot(
                original_center[0] - analysis.selected_center[0],
                original_center[1] - analysis.selected_center[1],
            ),
            "map_mask_state_raw_center": list(state_center) if state_center else None,
            "state_vs_same_capture_original_note": (
                "state may come from the immediately preceding RPC capture"
            ),
            "raw_candidates": raw_candidates,
            "local_candidates": local_candidates,
            "known_point": (
                {
                    "name": known_point.name,
                    "image_x": known_point.image_x,
                    "image_y": known_point.image_y,
                }
                if known_point is not None
                else None
            ),
            "files": written,
        }
        report_path = output_dir / f"{prefix}-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written["report"] = str(report_path)
        return {
            "status": "saved",
            "output_dir": str(output_dir),
            "files": written,
            "selected_center": list(analysis.selected_center),
            "selected_confidence": analysis.selected_confidence,
            "reported_global_top1_confidence": analysis.raw_top1_confidence,
            "top1_top2_margin": analysis.raw_top1_top2_margin,
            "selected_to_top1_distance": analysis.selected_to_raw_top1_distance,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "output_dir": str(output_dir),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _write_debug_image(path: Path, image: Any) -> None:
    import cv2

    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"cv2.imwrite returned false for {path}")


def _crop_map_area(image: Any, viewport: dict[str, Any]) -> Any:
    frame = image
    height, width = frame.shape[:2]
    left = max(0, int(round(float(viewport.get("screen_left") or 0))))
    top = max(0, int(round(float(viewport.get("screen_top") or 0))))
    crop_width = int(round(float(viewport.get("screen_width") or width)))
    crop_height = int(round(float(viewport.get("screen_height") or height)))
    right = min(width, left + max(1, crop_width))
    bottom = min(height, top + max(1, crop_height))
    if right <= left or bottom <= top:
        raise RuntimeError("map area crop is empty")
    return frame[top:bottom, left:right].copy()


def _enrich_match_candidates(
    candidates: list[dict[str, float]],
    points: list[Any],
    known_point: Any | None,
) -> list[dict[str, Any]]:
    enriched = []
    for candidate in candidates:
        center_x = float(candidate["center_x"])
        center_y = float(candidate["center_y"])
        nearest = min(
            points,
            key=lambda point: math.hypot(
                point.image_x - center_x,
                point.image_y - center_y,
            ),
            default=None,
        )
        known_distance = (
            math.hypot(
                known_point.image_x - center_x,
                known_point.image_y - center_y,
            )
            if known_point is not None
            else None
        )
        enriched.append(
            {
                **candidate,
                "rank": int(candidate["rank"]),
                "nearest_loaded_point_name": nearest.name if nearest else "",
                "nearest_loaded_point_image_x": nearest.image_x if nearest else None,
                "nearest_loaded_point_image_y": nearest.image_y if nearest else None,
                "distance_to_nearest_point": (
                    math.hypot(
                        nearest.image_x - center_x,
                        nearest.image_y - center_y,
                    )
                    if nearest
                    else math.inf
                ),
                "known_point_distance": known_distance,
                "near_known_point": (
                    known_distance is not None and known_distance <= 3000.0
                ),
            }
        )
    return enriched


def _annotate_match_asset(
    asset: Any,
    raw_candidates: list[dict[str, Any]],
    local_candidates: list[dict[str, Any]],
    selected_center: tuple[float, float],
) -> Any:
    import cv2
    import numpy as np

    grayscale = np.asarray(asset)
    annotated = (
        cv2.cvtColor(grayscale, cv2.COLOR_GRAY2BGR)
        if grayscale.ndim == 2
        else grayscale.copy()
    )
    for candidate in raw_candidates:
        position = (
            int(round(candidate["center_x"] * 0.125)),
            int(round(candidate["center_y"] * 0.125)),
        )
        cv2.circle(annotated, position, 18, (255, 120, 0), 3)
        cv2.putText(
            annotated,
            f"R{candidate['rank']} {candidate['confidence']:.3f}",
            (position[0] + 20, position[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 120, 0),
            2,
            cv2.LINE_AA,
        )
    for candidate in local_candidates:
        position = (
            int(round(candidate["center_x"] * 0.125)),
            int(round(candidate["center_y"] * 0.125)),
        )
        cv2.circle(annotated, position, 12, (0, 220, 255), 2)
        cv2.putText(
            annotated,
            f"L{candidate['rank']}",
            (position[0] + 12, position[1] + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 220, 255),
            1,
            cv2.LINE_AA,
        )
    selected = (
        int(round(selected_center[0] * 0.125)),
        int(round(selected_center[1] * 0.125)),
    )
    cv2.drawMarker(
        annotated,
        selected,
        (0, 0, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=40,
        thickness=3,
    )
    return annotated


def _pair_from_state(
    state: dict[str, Any],
    x_key: str,
    y_key: str,
) -> tuple[float, float] | None:
    try:
        x = float(state[x_key])
        y = float(state[y_key])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _stability_environment() -> dict[str, str]:
    names = (
        "WHIMBOX_MAP_MASK_VIEWPORT_MAX_CENTER_JUMP",
        "WHIMBOX_MAP_MASK_VIEWPORT_CONFIRM_FRAMES",
        "WHIMBOX_MAP_MASK_VIEWPORT_PENDING_RADIUS",
        "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING",
        "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_MODE",
        "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_ALPHA",
        "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_MAX_DISTANCE",
        "WHIMBOX_MAP_MASK_VIEWPORT_TRACKING_RADIUS",
        "WHIMBOX_MAP_MASK_VIEWPORT_REACQUIRE_CONFIRM_FRAMES",
        "WHIMBOX_MAP_MASK_VIEWPORT_REACQUIRE_PENDING_RADIUS",
        "WHIMBOX_MAP_MASK_VIEWPORT_MOTION_DIFF_THRESHOLD",
        "WHIMBOX_MAP_MASK_VIEWPORT_CONFIDENCE_THRESHOLD",
        "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_CHECK_INTERVAL_MS",
        "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_CHECK_DELTA_THRESHOLD",
        "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_MATCH_MIN_MARGIN",
        "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_SELECTED_TOP1_MAX_DISTANCE",
        "WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_X",
        "WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_Y",
        "WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_MAX_DISTANCE",
        "WHIMBOX_MAP_MASK_VIEWPORT_REJECT_FAR_EXPECTED_CENTER",
    )
    return {name: os.environ.get(name, "") for name in names}


def _format_visible_points(points: list[Any]) -> str:
    visible = []
    for item in points[:20]:
        if not isinstance(item, dict):
            continue
        visible.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "label_id": item.get("label_id"),
                "screen_x": item.get("screen_x"),
                "screen_y": item.get("screen_y"),
                "map_name": item.get("map_name"),
            }
        )
    return f"  visible_points={json.dumps(visible, ensure_ascii=False)}"


def _format_known_point(
    service: Any,
    point_name: str,
    viewport: dict[str, Any],
) -> str:
    if not viewport:
        return f"  known_point={point_name!r} status=no-viewport"
    try:
        map_name = str(viewport.get("map_name") or "")
        matches = [
            point
            for point in service._list_points(map_name=map_name or None)
            if point.name == point_name
        ]
        if not matches:
            return f"  known_point={point_name!r} status=not-loaded"
        point = matches[0]
        image_width = float(viewport["image_width"])
        image_height = float(viewport["image_height"])
        screen_width = float(viewport["screen_width"])
        screen_height = float(viewport["screen_height"])
        image_left = float(viewport["image_left"])
        image_top = float(viewport["image_top"])
        screen_left = float(viewport["screen_left"])
        screen_top = float(viewport["screen_top"])
        screen_x = screen_left + (point.image_x - image_left) / image_width * screen_width
        screen_y = screen_top + (point.image_y - image_top) / image_height * screen_height
        center_x = screen_left + screen_width / 2
        center_y = screen_top + screen_height / 2
        return (
            f"  known_point={point.name!r} "
            f"image=({point.image_x:.1f},{point.image_y:.1f}) "
            f"screen=({screen_x:.1f},{screen_y:.1f}) "
            f"screen_center_delta=({screen_x - center_x:.1f},"
            f"{screen_y - center_y:.1f})"
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"  known_point={point_name!r} status=error "
            f"error={type(exc).__name__}: {exc}"
        )


def _capture_status(state: dict[str, Any]) -> str:
    if not state.get("is_bigmap_open"):
        return "not-run"
    source = str(state.get("viewport_source") or "")
    error = str(state.get("viewport_detection_error") or "")
    if source == "hybrid-auto-center":
        return "ok"
    if "capture" in error.lower():
        return "failed"
    if error:
        return "ok-with-detection-error"
    return "fallback"


def _bool_word(value: Any) -> str:
    return "true" if bool(value) else "false"


def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:.{digits}f}"


if __name__ == "__main__":
    raise SystemExit(main())
