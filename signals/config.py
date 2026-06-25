"""Configuration loader.

Loads ``config.yaml`` (data sources, paths, universes, timeframes). The
scoring weights/thresholds added in later phases live in the same file
under a ``scoring:`` block. Environment variables override secrets
(notably ``POLYGON_API_KEY``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Minimal parser (no dependency). Existing environment variables are
    NOT overridden, so a real env var always wins over the file.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


@dataclass
class Config:
    data_dir: str = "data"
    polygon_api_key: str = ""
    crypto_source: str = "binance"
    stock_live_source: str = "polygon"
    stock_history_source: str = "yahoo"
    history_years: int = 10
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        _load_dotenv()  # pick up POLYGON_API_KEY etc. from .env if present
        data: dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}

        d = data.get("data", {})
        cfg = cls(
            data_dir=os.environ.get("SIGNALS_DATA_DIR", d.get("data_dir", "data")),
            polygon_api_key=os.environ.get("POLYGON_API_KEY",
                                           d.get("polygon_api_key", "")),
            crypto_source=d.get("crypto_source", "binance"),
            stock_live_source=d.get("stock_live_source", "polygon"),
            stock_history_source=d.get("stock_history_source", "yahoo"),
            history_years=int(d.get("history_years", 10)),
            raw=data,
        )
        return cfg
