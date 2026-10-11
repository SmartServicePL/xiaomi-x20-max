"""Diagnostyka nie ujawnia identyfikatora chmury ani nazw pokoi."""

from __future__ import annotations

import json

from custom_components.xiaomi_x20_max.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import DID


async def test_diagnostics_redact_did_and_room_names(hass, loaded) -> None:
    data = await async_get_config_entry_diagnostics(hass, loaded)
    text = json.dumps(data, ensure_ascii=False)
    assert DID not in text
    assert "Kuchnia" not in text and "Przedsionek" not in text
    assert data["did"] == "**REDACTED**"
    assert data["rooms"] == [
        {"id": 12, "name": "**REDACTED**"},
        {"id": 13, "name": "**REDACTED**"},
        {"id": 14, "name": "**REDACTED**"},
    ]
    assert data["status"] == 2
