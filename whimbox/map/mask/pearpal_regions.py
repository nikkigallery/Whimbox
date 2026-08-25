from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_PEARPAL_REGION = "cn"


@dataclass(frozen=True, slots=True)
class PearPalRegion:
    name: str
    page_url: str
    api_base: str
    asset_base: str
    client_name: str
    client_id: int

    @property
    def user_info_url(self) -> str:
        return f"{self.api_base}/v1/strategy/map/user/info"


REGIONS = {
    "cn": PearPalRegion(
        name="cn",
        page_url="https://myl.nuanpaper.com/tools/map",
        api_base="https://myl-api.nuanpaper.com",
        asset_base="https://assets.papegames.com",
        client_name="nikki5CN",
        client_id=1106,
    ),
    "oversea": PearPalRegion(
        name="oversea",
        page_url="https://pearpal.infoldgames.com/tools/map",
        api_base="https://pearpal-api.infoldgames.com",
        asset_base="https://assets.infoldgames.com",
        client_name="nikki5Other",
        client_id=1116,
    ),
}


def normalize_pearpal_region(value: Any) -> str:
    region = str(value or DEFAULT_PEARPAL_REGION).strip().lower()
    aliases = {
        "global": "oversea",
        "international": "oversea",
    }
    region = aliases.get(region, region)
    if region not in REGIONS:
        raise ValueError(f"unsupported PearPal region: {value}")
    return region


def get_pearpal_region(value: Any) -> PearPalRegion:
    return REGIONS[normalize_pearpal_region(value)]
