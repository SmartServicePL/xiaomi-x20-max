"""Tłumaczenia: komplet kluczy PL i placeholdery komunikatów błędów."""

from __future__ import annotations

import json
from pathlib import Path
import re

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "xiaomi_x20_max"


def load(name: str) -> dict:
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def keys(data: dict, prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, value in data.items():
        found.add(prefix + key)
        if isinstance(value, dict):
            found |= keys(value, f"{prefix}{key}.")
    return found


def test_english_matches_strings() -> None:
    assert load("translations/en.json") == load("strings.json")


def test_polish_has_every_key() -> None:
    assert keys(load("translations/pl.json")) == keys(load("strings.json"))


def test_every_exception_key_is_translated() -> None:
    used: set[str] = set()
    for path in INTEGRATION.glob("*.py"):
        used |= set(
            re.findall(
                r'translation_key="([a-z_]+)"', path.read_text(encoding="utf-8")
            )
        )
    strings = load("strings.json")
    polish = load("translations/pl.json")
    exceptions = set(strings["exceptions"])
    assert exceptions <= used
    for key in exceptions:
        english = strings["exceptions"][key]["message"]
        translated = polish["exceptions"][key]["message"]
        assert set(re.findall(r"{(\w+)}", english)) == set(
            re.findall(r"{(\w+)}", translated)
        )
