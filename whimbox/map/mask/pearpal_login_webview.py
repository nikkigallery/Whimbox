from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any


_READ_STORAGE_SCRIPT = """
(() => {
  if (location.hostname !== 'myl.nuanpaper.com') return null;
  return {
    momoToken: localStorage.getItem('momoToken') || '',
    momoNid: localStorage.getItem('momoNid') || ''
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Whimbox PearPal login WebView")
    parser.add_argument("--url", required=True)
    parser.add_argument("--storage-path", required=True)
    args = parser.parse_args()

    if args.url != "https://myl.nuanpaper.com/tools/map":
        return _emit({"status": "error", "error": "refusing unexpected login URL"}, 1)
    storage_path = Path(args.storage_path).resolve()
    storage_path.mkdir(parents=True, exist_ok=True)

    try:
        import webview
    except Exception as exc:
        return _emit(
            {
                "status": "error",
                "error": f"pywebview is unavailable: {type(exc).__name__}: {exc}",
            },
            1,
        )

    result: dict[str, Any] = {}
    result_lock = threading.Lock()
    window_closed = threading.Event()
    window = webview.create_window(
        "Whimbox - PearPal Login",
        args.url,
        width=1100,
        height=760,
        min_size=(800, 600),
    )
    if window is None:
        return _emit({"status": "error", "error": "failed to create WebView"}, 1)
    window.events.closed += lambda: window_closed.set()

    def poll_storage(target: Any) -> None:
        while not window_closed.is_set():
            with result_lock:
                if result:
                    return
            try:
                value = target.evaluate_js(_READ_STORAGE_SCRIPT)
            except Exception:
                window_closed.wait(0.4)
                continue
            if (
                isinstance(value, dict)
                and value.get("momoToken")
                and value.get("momoNid")
            ):
                with result_lock:
                    result.update(
                        {
                            "status": "ok",
                            "momoToken": str(value["momoToken"]),
                            "momoNid": str(value["momoNid"]),
                        }
                    )
                target.destroy()
                return
            window_closed.wait(0.4)

    try:
        webview.start(
            poll_storage,
            (window,),
            gui="edgechromium",
            private_mode=False,
            storage_path=str(storage_path),
        )
    except Exception as exc:
        return _emit(
            {"status": "error", "error": f"WebView failed: {type(exc).__name__}: {exc}"},
            1,
        )
    with result_lock:
        final_result = dict(result) if result else {"status": "cancelled"}
    return _emit(final_result, 0)


def _emit(payload: dict[str, Any], exit_code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
