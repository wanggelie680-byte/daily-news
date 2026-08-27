"""Load project configuration."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_json(relative_path: str):
    path = ROOT / relative_path
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_settings() -> dict:
    return load_json("config/settings.json")


def load_feeds() -> list[dict]:
    return load_json("config/feeds.json")["feeds"]
