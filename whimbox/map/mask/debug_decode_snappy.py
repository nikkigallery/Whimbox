from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from whimbox.map.mask.pearpal_debug import (  # noqa: E402
    decode_snappy_json,
    default_cache_dir,
)


def main() -> int:
    _configure_utf8_console()
    args = _build_parser().parse_args()
    inputs = _resolve_inputs(args.inputs, args.cache_dir)
    if args.output and len(inputs) != 1:
        raise SystemExit("--output can only be used with exactly one input file")

    output_dir = Path(args.output_dir).expanduser().resolve()
    failures = 0
    for input_path in inputs:
        try:
            payload = decode_snappy_json(input_path.read_bytes())
            _print_summary(input_path, payload, args.sample)
            if not args.no_output:
                output_path = (
                    Path(args.output).expanduser().resolve()
                    if args.output
                    else output_dir / f"{input_path.stem}.decoded.json"
                )
                _write_json(output_path, payload, compact=args.compact)
                print(f"decoded JSON: {output_path}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(
                f"failed: {input_path}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    return 1 if failures else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decode raw PearPal Snappy response files without applying provider "
            "sanitization, catalog filtering, stage expansion, or coordinate conversion."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=(
            "Snappy files to decode. If omitted, all *.snappy files in the "
            "Whimbox PearPal cache are decoded."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(default_cache_dir()),
        help="cache directory used when no input files are supplied",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="output JSON path; valid only for one input file",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPOSITORY_ROOT / "output" / "pearpal-snappy"),
        help="directory for decoded JSON files",
    )
    parser.add_argument(
        "--sample",
        type=_non_negative_int,
        default=3,
        help="number of raw records to print as a console sample",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="only print summaries and samples; do not write JSON files",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="write compact JSON instead of indented JSON",
    )
    return parser


def _resolve_inputs(values: list[str], cache_dir: str) -> list[Path]:
    if values:
        paths = [Path(value).expanduser().resolve() for value in values]
    else:
        root = Path(cache_dir).expanduser().resolve()
        paths = sorted(root.glob("*.snappy"))
        if not paths:
            raise SystemExit(f"no .snappy files found in cache directory: {root}")
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(
            "input file does not exist: " + ", ".join(str(path) for path in missing)
        )
    return paths


def _print_summary(path: Path, payload: dict[str, Any], sample_count: int) -> None:
    print()
    print(f"source: {path}")
    print(f"bytes: {path.stat().st_size}")
    print(f"top-level keys: {sorted(payload)}")

    items = payload.get("list")
    if isinstance(items, list):
        print(f"list records: {len(items)}")
        _print_json_sample("list sample", items[:sample_count])

    stages = payload.get("stages")
    if isinstance(stages, dict):
        child_count = sum(
            len(children) for children in stages.values() if isinstance(children, list)
        )
        print(f"stage records: {len(stages)} stages / {child_count} children")
        stage_sample: dict[str, Any] = {}
        for stage_id, children in stages.items():
            stage_sample[str(stage_id)] = (
                children[:sample_count] if isinstance(children, list) else children
            )
            if len(stage_sample) >= sample_count:
                break
        _print_json_sample("stage sample", stage_sample)

    if not isinstance(items, list) and not isinstance(stages, dict):
        _print_json_sample("payload sample", payload)


def _print_json_sample(label: str, value: Any) -> None:
    print(f"{label}:")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _write_json(path: Path, payload: dict[str, Any], *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(content + "\n", encoding="utf-8")


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
