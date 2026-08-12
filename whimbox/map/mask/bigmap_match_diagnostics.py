from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from whimbox.map.detection.bigmap import predict_bigmap
from whimbox.map.detection.cvars import BIGMAP_SEARCH_SCALE
from whimbox.map.detection.map_assets import MAP_ASSETS_DICT


@dataclass(slots=True)
class BigMapMatchAnalysis:
    map_name: str
    asset_name: str
    asset_path: str
    input_shape: tuple[int, ...]
    preprocessed_shape: tuple[int, ...]
    asset_shape: tuple[int, ...]
    result_shape: tuple[int, ...]
    resize_scale: float
    input_mean: float
    input_std: float
    input_min: float
    input_max: float
    selected_center: tuple[float, float]
    selected_confidence: float
    selected_local_score: float
    raw_top1_confidence: float
    raw_top2_confidence: float | None
    raw_top1_top2_margin: float | None
    selected_to_raw_top1_distance: float | None
    raw_candidates: list[dict[str, float]]
    local_candidates: list[dict[str, float]]
    preprocessed: np.ndarray
    result: np.ndarray
    local_maximum: np.ndarray
    asset: np.ndarray

    def to_report(self) -> dict[str, Any]:
        return {
            "map_name": self.map_name,
            "asset_name": self.asset_name,
            "asset_path": self.asset_path,
            "input_shape": list(self.input_shape),
            "preprocessed_shape": list(self.preprocessed_shape),
            "asset_shape": list(self.asset_shape),
            "result_shape": list(self.result_shape),
            "resize_scale": self.resize_scale,
            "input_mean": self.input_mean,
            "input_std": self.input_std,
            "input_min": self.input_min,
            "input_max": self.input_max,
            "selected_center": list(self.selected_center),
            "selected_confidence": self.selected_confidence,
            "selected_local_score": self.selected_local_score,
            "raw_top1_confidence": self.raw_top1_confidence,
            "raw_top2_confidence": self.raw_top2_confidence,
            "raw_top1_top2_margin": self.raw_top1_top2_margin,
            "selected_to_raw_top1_distance": self.selected_to_raw_top1_distance,
            "raw_candidates": self.raw_candidates,
            "local_candidates": self.local_candidates,
        }


def analyze_bigmap_match(
    image: Any,
    map_name: str,
    *,
    top_k: int = 5,
    nms_radius_png: float = 300.0,
) -> BigMapMatchAnalysis:
    source = np.asarray(image)
    prediction = predict_bigmap(source, map_name)
    resize_scale = prediction.resize_scale
    center_offset = prediction.center_offset
    preprocessed = prediction.preprocessed

    asset_entry = MAP_ASSETS_DICT[map_name]["luma_0125x"]
    asset = asset_entry.img
    result = prediction.result
    local_maximum = prediction.local_maximum
    raw_top1_confidence = prediction.similarity
    selected_local_score = prediction.similarity_local
    selected_result_location = prediction.selected_result_location
    selected_center_array = prediction.position
    selected_center = (
        float(selected_center_array[0]),
        float(selected_center_array[1]),
    )
    selected_confidence = _sample_result(result, selected_result_location)

    suppression_radius = max(
        1,
        int(round(nms_radius_png * BIGMAP_SEARCH_SCALE)),
    )
    raw_candidates = _extract_candidates(
        result,
        center_offset=center_offset,
        top_k=top_k,
        suppression_radius=suppression_radius,
        raw_result=result,
        score_name="confidence",
    )
    local_candidates = _extract_candidates(
        local_maximum,
        center_offset=center_offset,
        top_k=top_k,
        suppression_radius=suppression_radius,
        raw_result=result,
        score_name="local_score",
    )
    raw_top2_confidence = (
        float(raw_candidates[1]["confidence"])
        if len(raw_candidates) > 1
        else None
    )
    margin = (
        float(raw_candidates[0]["confidence"]) - raw_top2_confidence
        if raw_candidates and raw_top2_confidence is not None
        else None
    )
    raw_top1_center = (
        (
            float(raw_candidates[0]["center_x"]),
            float(raw_candidates[0]["center_y"]),
        )
        if raw_candidates
        else None
    )
    selected_to_raw_top1_distance = (
        math.hypot(
            selected_center[0] - raw_top1_center[0],
            selected_center[1] - raw_top1_center[1],
        )
        if raw_top1_center is not None
        else None
    )

    return BigMapMatchAnalysis(
        map_name=map_name,
        asset_name=str(getattr(asset_entry, "name", "luma_0125x")),
        asset_path=str(getattr(asset_entry, "path", "")),
        input_shape=tuple(int(value) for value in source.shape),
        preprocessed_shape=tuple(int(value) for value in preprocessed.shape),
        asset_shape=tuple(int(value) for value in asset.shape),
        result_shape=tuple(int(value) for value in result.shape),
        resize_scale=resize_scale,
        input_mean=float(np.mean(source)),
        input_std=float(np.std(source)),
        input_min=float(np.min(source)),
        input_max=float(np.max(source)),
        selected_center=selected_center,
        selected_confidence=selected_confidence,
        selected_local_score=float(selected_local_score),
        raw_top1_confidence=float(raw_top1_confidence),
        raw_top2_confidence=raw_top2_confidence,
        raw_top1_top2_margin=margin,
        selected_to_raw_top1_distance=selected_to_raw_top1_distance,
        raw_candidates=raw_candidates,
        local_candidates=local_candidates,
        preprocessed=preprocessed,
        result=result,
        local_maximum=local_maximum,
        asset=asset,
    )


def _extract_candidates(
    score_map: np.ndarray,
    *,
    center_offset: np.ndarray,
    top_k: int,
    suppression_radius: int,
    raw_result: np.ndarray,
    score_name: str,
) -> list[dict[str, float]]:
    working = np.asarray(score_map, dtype=np.float32).copy()
    candidates: list[dict[str, float]] = []
    for rank in range(1, max(1, top_k) + 1):
        _, score, _, location = cv2.minMaxLoc(working)
        if not math.isfinite(score):
            break
        x, y = location
        center = (
            np.asarray((x, y), dtype=np.float64) + center_offset
        ) / BIGMAP_SEARCH_SCALE
        candidate = {
            "rank": float(rank),
            "center_x": float(center[0]),
            "center_y": float(center[1]),
            "confidence": float(raw_result[y, x]),
            score_name: float(score),
            "result_x": float(x),
            "result_y": float(y),
        }
        candidates.append(candidate)
        cv2.circle(
            working,
            (x, y),
            suppression_radius,
            float("-inf"),
            thickness=-1,
        )
    return candidates


def _sample_result(
    result: np.ndarray,
    location: np.ndarray,
) -> float:
    x = min(max(int(round(float(location[0]))), 0), result.shape[1] - 1)
    y = min(max(int(round(float(location[1]))), 0), result.shape[0] - 1)
    return float(result[y, x])
