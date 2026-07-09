from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def package_map_mask_dir() -> Path:
    try:
        return Path(str(files("whimbox").joinpath("assets", "map_mask")))
    except Exception:
        return Path(__file__).resolve().parents[2] / "assets" / "map_mask"


def repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "whimbox").is_dir():
            return parent
    return current.parents[3]


def development_map_mask_dir() -> Path:
    return repository_root() / "assets" / "map_mask"


def first_existing_resource(file_name: str) -> Path | None:
    for directory in (package_map_mask_dir(), development_map_mask_dir()):
        candidate = directory / file_name
        if candidate.is_file():
            return candidate
    return None
