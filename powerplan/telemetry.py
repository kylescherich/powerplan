"""Replayed telemetry: utility demand-response limits (and, later, GPU power).

Files are read from disk in their real formats; nothing here touches the
network. Stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .models import Fleet


# ---------------------------------------------------------------------------
# demand-response events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DREvent:
    """A utility demand-response limit: `site_id` may draw at most `limit_kw`
    during hours ``[start_hour, end_hour)``."""

    site_id: str
    start_hour: int
    end_hour: int
    limit_kw: float


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_event(index: int, raw) -> DREvent:
    if not isinstance(raw, dict):
        raise ValueError(f"event {index}: must be an object")
    for key in ("site_id", "start_hour", "end_hour", "limit_kw"):
        if key not in raw:
            raise ValueError(f"event {index}: missing {key}")

    site_id = raw["site_id"]
    start = raw["start_hour"]
    end = raw["end_hour"]
    limit = raw["limit_kw"]

    if not isinstance(site_id, str) or not site_id:
        raise ValueError(f"event {index}: site_id must be a non-empty string")
    if not _is_int(start) or not _is_int(end):
        raise ValueError(f"event {index}: start_hour and end_hour must be integers")
    if not 0 <= start < end <= 24:
        raise ValueError(
            f"event {index}: hours must satisfy 0 <= start_hour < end_hour <= 24, "
            f"got {start}..{end}"
        )
    if not _is_number(limit) or not limit >= 0:
        raise ValueError(f"event {index}: limit_kw must be a number >= 0")

    return DREvent(
        site_id=site_id,
        start_hour=start,
        end_hour=end,
        limit_kw=float(limit),
    )


def parse_dr_events(text: str) -> list[DREvent]:
    """Parse ``{"events": [{"site_id", "start_hour", "end_hour", "limit_kw"}, ...]}``.

    Raises `ValueError` naming the event index for any invalid event.
    """
    raw = json.loads(text)
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise ValueError('demand-response file must be {"events": [...]}')
    return [_parse_event(i, e) for i, e in enumerate(raw["events"])]


def apply_dr(fleet: Fleet, events: list[DREvent]) -> None:
    """Set each site's hourly power limit from `events`.

    Every hour in ``[start_hour, end_hour)`` gets the event's limit; where
    limits overlap, the lower one is kept. An unknown site raises `ValueError`
    naming it, before the fleet is changed.
    """
    sites = {}
    for event in events:
        try:
            sites[event.site_id] = fleet.site(event.site_id)
        except KeyError:
            raise ValueError(
                f"demand-response event for unknown site {event.site_id}"
            ) from None

    for event in events:
        limits = sites[event.site_id].power_limit_kw_by_hour
        for hour in range(event.start_hour, event.end_hour):
            current = limits[hour]
            if current is None or event.limit_kw < current:
                limits[hour] = event.limit_kw
