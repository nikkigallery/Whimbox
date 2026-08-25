from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any


_USER_INFO_URL = "https://myl-api.nuanpaper.com/v1/strategy/map/user/info"
_DEFAULT_CLIENT_ID = 1106
_MAX_USER_INFO_BYTES = 4 * 1024 * 1024
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,512}$")
_OPENID_PATTERN = re.compile(r"^\d{1,32}$")


class PearPalAuthError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PearPalCredentials:
    token: str
    openid: str

    @property
    def masked_openid(self) -> str:
        if len(self.openid) <= 4:
            return "*" * len(self.openid)
        return f"{self.openid[:2]}{'*' * (len(self.openid) - 4)}{self.openid[-2:]}"


@dataclass(frozen=True, slots=True)
class PearPalAwardedState:
    star_ids: frozenset[str]
    box_ids: frozenset[str]
    dewdrop_ids: frozenset[str] = frozenset()
    read_ids: frozenset[str] = frozenset()


class PearPalUserClient:
    def __init__(self, *, client_id: int = _DEFAULT_CLIENT_ID) -> None:
        self.client_id = int(client_id)

    def fetch_awarded_state(
        self,
        credentials: PearPalCredentials,
    ) -> PearPalAwardedState:
        body = json.dumps(
            {
                "client_id": self.client_id,
                "token": credentials.token,
                "openid": credentials.openid,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            _USER_INFO_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Whimbox-PearPal-User-State/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.geturl() != _USER_INFO_URL:
                    raise PearPalAuthError("user info request was redirected")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > _MAX_USER_INFO_BYTES:
                    raise PearPalAuthError("user info response is too large")
                raw = response.read(_MAX_USER_INFO_BYTES + 1)
        except PearPalAuthError:
            raise
        except Exception as exc:
            raise PearPalAuthError(
                f"failed to fetch PearPal user state: {type(exc).__name__}: {exc}"
            ) from exc
        if len(raw) > _MAX_USER_INFO_BYTES:
            raise PearPalAuthError("user info response is too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PearPalAuthError("user info response is not valid JSON") from exc
        return decode_user_info(payload)


def decode_user_info(payload: Any) -> PearPalAwardedState:
    if not isinstance(payload, dict):
        raise PearPalAuthError("user info response root must be an object")
    if payload.get("code") != 0:
        message = str(payload.get("info") or "unknown API error")
        raise PearPalAuthError(f"PearPal user info rejected the session: {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise PearPalAuthError("user info response is missing data")
    return PearPalAwardedState(
        star_ids=_decode_id_set(data.get("star"), "star"),
        box_ids=_decode_id_set(data.get("box"), "box"),
        dewdrop_ids=_decode_id_set(data.get("dewdrop"), "dewdrop"),
        read_ids=_decode_id_set(data.get("read"), "read"),
    )


def parse_login_storage(momo_token: Any, momo_nid: Any) -> PearPalCredentials:
    raw_token = momo_token
    if not isinstance(raw_token, str):
        raise PearPalAuthError("momoToken is missing from Local Storage")
    try:
        token_value = json.loads(raw_token)
    except json.JSONDecodeError as exc:
        raise PearPalAuthError("momoToken is not valid JSON") from exc
    token = token_value.get("token") if isinstance(token_value, dict) else None
    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        raise PearPalAuthError("momoToken.token has an invalid format")

    openid = _parse_momo_nid(momo_nid)
    return PearPalCredentials(token=token, openid=openid)


def _parse_momo_nid(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise PearPalAuthError("momoNid has an invalid format")

    decoded: Any = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise PearPalAuthError("momoNid has an invalid format")
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = raw

    if isinstance(decoded, dict):
        decoded = next(
            (decoded[key] for key in ("nid", "openid", "value") if key in decoded),
            None,
        )

    if isinstance(decoded, bool) or not isinstance(decoded, (int, str)):
        raise PearPalAuthError("momoNid has an invalid format")
    openid = str(decoded).strip()
    if not _OPENID_PATTERN.fullmatch(openid):
        raise PearPalAuthError("momoNid has an invalid format")
    return openid


def _decode_id_set(value: Any, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise PearPalAuthError(f"user info data.{label} must be a list")
    result: set[str] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            continue
        point_id = str(item).strip()
        if point_id and len(point_id) <= 64:
            result.add(point_id)
    return frozenset(result)
