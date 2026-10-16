"""A stdlib, OpenTelemetry-shaped span log.

No OpenTelemetry package or exporter is used. Finished spans are plain dicts
with exactly these keys: ``trace_id``, ``span_id``, ``parent_span_id``,
``name``, ``start_time_unix_nano``, ``end_time_unix_nano``, ``attributes`` and
``status``. They can be written as JSON lines with `Tracer.to_jsonl`.
"""

from __future__ import annotations

import json
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


class Tracer:
    """Collects finished spans in memory.

    ``clock()`` returns integer nanoseconds (default ``time.time_ns``).
    ``new_id(nbytes)`` returns a hex string of ``2 * nbytes`` characters
    (default ``secrets.token_hex``).
    """

    def __init__(
        self,
        clock: Callable[[], int] | None = None,
        new_id: Callable[[int], str] | None = None,
    ) -> None:
        self._clock = clock if clock is not None else time.time_ns
        self._new_id = new_id if new_id is not None else secrets.token_hex
        self._open: list[tuple[str, str]] = []  # (trace_id, span_id)
        self.spans: list[dict] = []

    @contextmanager
    def span(self, name: str, **attributes) -> Iterator[dict]:
        """Open a span; yields its attributes dict, which may be added to.

        The span is appended to ``spans`` when it ends. If the block raises,
        the span is recorded with status ``"ERROR"`` and the exception
        propagates unchanged.
        """
        if self._open:
            trace_id, parent_span_id = self._open[-1]
        else:
            trace_id = self._new_id(16)
            parent_span_id = None
        span_id = self._new_id(8)
        attrs = dict(attributes)
        start = self._clock()
        self._open.append((trace_id, span_id))
        status = "OK"
        try:
            yield attrs
        except BaseException as exc:
            status = "ERROR"
            attrs["exception.type"] = type(exc).__name__
            raise
        finally:
            end = self._clock()
            self._open.pop()
            self.spans.append(
                {
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "name": name,
                    "start_time_unix_nano": start,
                    "end_time_unix_nano": end,
                    "attributes": attrs,
                    "status": status,
                }
            )

    def to_jsonl(self, path: str | Path) -> int:
        """Write one JSON object per span to ``path``; return the count."""
        with open(path, "w", encoding="utf-8") as fh:
            for span in self.spans:
                fh.write(json.dumps(span, sort_keys=True) + "\n")
        return len(self.spans)
