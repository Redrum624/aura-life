"""
Device location store — persists the fuzzed GPS point the Android app POSTs.

Privacy contract:
  - The server stores ONLY the fuzzed (~40 km) point the client sends.
  - No reverse-geocode, no fine-grained coordinates are ever kept here.
  - File: <user_data_root>/.device_location.json

Public API:
  save_device_location(lat, lon) -> None
  get_device_location() -> dict | None   # {lat, lon, updated_at} or None
  clear_device_location() -> None        # for tests / admin
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_FILENAME = ".device_location.json"


def _store_path() -> Path:
    from aura_life.hooks import get_user_data_root
    return get_user_data_root() / _FILENAME


def save_device_location(lat: float, lon: float, *, path: Optional[Path] = None) -> None:
    """Persist fuzzed GPS point to the device-location store.

    Safe-fail: any write error is logged and swallowed.
    ``path`` overrides the default location (used in tests).
    """
    p = path if path is not None else _store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lat": lat,
            "lon": lon,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        p.write_text(json.dumps(payload), encoding="utf-8")
        logger.info("device_location: stored fuzzed point (%.4f, %.4f)", lat, lon)
    except Exception as exc:
        logger.warning("device_location: save failed: %s", exc)


def get_device_location(*, path: Optional[Path] = None) -> Optional[dict]:
    """Return stored device location or None if not set / unreadable.

    Returns dict with keys: lat (float), lon (float), updated_at (str ISO-8601).
    ``path`` overrides the default location (used in tests).
    """
    p = path if path is not None else _store_path()
    try:
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            return None
        return {"lat": float(lat), "lon": float(lon), "updated_at": data.get("updated_at", "")}
    except Exception as exc:
        logger.warning("device_location: read failed: %s", exc)
        return None


def clear_device_location(*, path: Optional[Path] = None) -> None:
    """Remove the stored device location (for tests / reset)."""
    p = path if path is not None else _store_path()
    try:
        if p.exists():
            p.unlink()
    except Exception as exc:
        logger.warning("device_location: clear failed: %s", exc)
