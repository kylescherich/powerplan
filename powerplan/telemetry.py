"""Replayed telemetry: utility demand-response limits (and, later, GPU power).

Files are read from disk in their real formats; nothing here touches the
network. Stdlib only.
"""

from __future__ import annotations

import json
import math
import re
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


# ---------------------------------------------------------------------------
# GPU power readings (dcgm-exporter / Prometheus text exposition)
# ---------------------------------------------------------------------------

POWER = "DCGM_FI_DEV_POWER_USAGE"  # watts

_NAME_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
_LABEL_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n"}


def _skip_space(line: str, pos: int) -> int:
    while pos < len(line) and line[pos] in " \t":
        pos += 1
    return pos


def _parse_labels(line: str, pos: int) -> tuple[dict[str, str], int]:
    """Parse a label set; `pos` is just after the opening brace.

    Returns the labels and the position just after the closing brace.
    """
    labels: dict[str, str] = {}
    n = len(line)
    while True:
        pos = _skip_space(line, pos)
        if pos >= n:
            raise ValueError("unterminated label set")
        if line[pos] == "}":
            return labels, pos + 1

        match = _LABEL_RE.match(line, pos)
        if not match:
            raise ValueError("malformed labels")
        name = match.group()
        pos = _skip_space(line, match.end())
        if pos >= n or line[pos] != "=":
            raise ValueError(f"malformed labels: expected '=' after {name}")
        pos = _skip_space(line, pos + 1)
        if pos >= n or line[pos] != '"':
            raise ValueError(f"malformed labels: value of {name} must be quoted")
        pos += 1

        chars: list[str] = []
        while True:
            if pos >= n:
                raise ValueError(f"malformed labels: unterminated value of {name}")
            char = line[pos]
            if char == '"':
                pos += 1
                break
            if char == "\\":
                if pos + 1 >= n or line[pos + 1] not in _ESCAPES:
                    raise ValueError(f"malformed labels: invalid escape in {name}")
                chars.append(_ESCAPES[line[pos + 1]])
                pos += 2
            else:
                chars.append(char)
                pos += 1
        labels[name] = "".join(chars)

        pos = _skip_space(line, pos)
        if pos < n and line[pos] == ",":
            pos += 1
        elif pos < n and line[pos] == "}":
            pass
        else:
            raise ValueError("malformed labels")


def _parse_sample(line: str) -> tuple[str, dict[str, str], float]:
    match = _NAME_RE.match(line)
    if not match:
        raise ValueError("not a sample")
    name = match.group()
    pos = match.end()

    labels: dict[str, str] = {}
    if pos < len(line) and line[pos] == "{":
        labels, pos = _parse_labels(line, pos + 1)

    tokens = line[pos:].split()
    if len(tokens) not in (1, 2):
        raise ValueError("expected a value and an optional timestamp")
    try:
        value = float(tokens[0])
    except ValueError:
        raise ValueError(f"non-numeric value {tokens[0]!r}") from None
    if len(tokens) == 2:
        try:
            int(tokens[1])
        except ValueError:
            raise ValueError(f"invalid timestamp {tokens[1]!r}") from None
    return name, labels, value


def parse_prometheus(text: str) -> list[tuple[str, dict[str, str], float]]:
    """Parse Prometheus text exposition into ``(name, labels, value)`` tuples.

    Blank lines and ``#`` comment lines are skipped; an optional integer
    timestamp is ignored. Any other malformed line raises `ValueError`
    containing ``line N`` (1-based).
    """
    samples = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            samples.append(_parse_sample(line))
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from None
    return samples


def gpu_it_kw_by_site(samples) -> dict[str, float]:
    """Sum `POWER` samples per ``site`` label, in kW; other metrics are ignored.

    A `POWER` sample without a ``site`` label, or with a non-finite value,
    raises `ValueError`.
    """
    watts_by_site: dict[str, float] = {}
    for name, labels, value in samples:
        if name != POWER:
            continue
        site = labels.get("site")
        if not site:
            raise ValueError(f"{POWER} sample has no site label: {labels}")
        if not math.isfinite(value):
            raise ValueError(f"{POWER} sample for {site} is not finite: {value}")
        watts_by_site[site] = watts_by_site.get(site, 0.0) + value
    return {site: watts / 1000.0 for site, watts in watts_by_site.items()}


def apply_gpu_power(fleet: Fleet, it_kw_by_site: dict[str, float]) -> None:
    """Add measured GPU IT draw (as facility power) to each site's baseline load.

    Each site's ``baseline_load_kw`` grows by ``kW * pue``. An unknown site
    raises `ValueError` naming it, before the fleet is changed. GPU
    availability is not changed (documented limitation).
    """
    sites = {}
    for site_id in it_kw_by_site:
        try:
            sites[site_id] = fleet.site(site_id)
        except KeyError:
            raise ValueError(f"GPU power for unknown site {site_id}") from None

    for site_id, it_kw in it_kw_by_site.items():
        site = sites[site_id]
        site.baseline_load_kw += it_kw * site.pue
