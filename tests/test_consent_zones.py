"""The banner's time-zone list covers every zone of the EEA, the UK and Switzerland."""

import os
import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

CONSENT_JS = REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "js" / "consent.js"
ZONE_TAB = Path("/usr/share/zoneinfo/zone.tab")
EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE"
EEA_EXTRA = "IS LI NO"
EU_REGIONS = "GF GP MQ MF RE YT AX"  # outermost regions and Åland have their own codes
UK_AND_NEIGHBOURS = "GB GI IM JE GG SJ CH"
COUNTRIES = set(f"{EU} {EEA_EXTRA} {EU_REGIONS} {UK_AND_NEIGHBOURS}".split())
UKRAINE = {
    "Europe/Kiev",
    "Europe/Kyiv",
    "Europe/Simferopol",
    "Europe/Uzhgorod",
    "Europe/Zaporozhye",
}


def listed_zones() -> set[str]:
    source = CONSENT_JS.read_text(encoding="utf-8")
    block = re.search(r"const EEA_TIME_ZONES = \[(.*?)\];", source, flags=re.DOTALL)
    assert block is not None, "EEA_TIME_ZONES not found in consent.js"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def zones_of_countries() -> set[str]:
    if not ZONE_TAB.exists():
        if os.environ.get("CI") == "true":
            pytest.fail(f"{ZONE_TAB} is required in CI")
        pytest.skip(f"{ZONE_TAB} is not available")
    zones = set()
    for line in ZONE_TAB.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            country, _, zone = line.split("\t")[:3]
            if country in COUNTRIES:
                zones.add(zone)
    return zones


def test_every_eea_uk_and_swiss_zone_is_listed() -> None:
    assert zones_of_countries() - listed_zones() == set()


def test_ukrainian_zones_are_not_listed() -> None:
    assert listed_zones() & UKRAINE == set()
