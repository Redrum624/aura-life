"""
Device location store — persists the fuzzed GPS point the Android app POSTs.

Privacy contract (what this module itself enforces):
  - Coordinates are rounded to STORED_PRECISION decimal places before they are
    written, and out-of-range values are rejected outright.
  - No reverse-geocode and no address is ever derived or kept here.
  - Nothing but the coarsened point and a timestamp is stored.
  - File: <user_data_root>/.device_location.json

Clients are expected to fuzz the point (~40 km) before sending it. This module
cannot verify that upstream fuzzing happened -- the rounding above is a floor on
stored precision, not a substitute for it.

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

# Decimal places retained on write. A hard ceiling on how precise a point this
# store can ever hold, whatever the caller passes in.
STORED_PRECISION = 2


def _store_path() -> Path:
    from aura_life.hooks import get_user_data_root
    return get_user_data_root() / _FILENAME


def save_device_location(lat: float, lon: float, *, path: Optional[Path] = None) -> None:
    """Persist a GPS point to the device-location store.

    The point is rounded to STORED_PRECISION decimals and range-checked before
    it is written, so the module's stated precision floor holds regardless of
    what the caller passes.  Out-of-range coordinates are rejected, not clamped.

    Safe-fail: any write error is logged and swallowed.
    ``path`` overrides the default location (used in tests).
    """
    p = path if path is not None else _store_path()
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        logger.warning("device_location: save rejected: coordinates are not numeric")
        return
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        # Never echo the offending values: they are user location data.
        logger.warning("device_location: save rejected: coordinates out of range")
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lat": round(lat_f, STORED_PRECISION),
            "lon": round(lon_f, STORED_PRECISION),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        p.write_text(json.dumps(payload), encoding="utf-8")
        # The point itself must never reach the host log stream.
        logger.debug("device_location: point stored")
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
