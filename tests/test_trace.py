import itertools
import json
import re

import pytest

from powerplan.trace import Tracer

SPAN_KEYS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "name",
    "start_time_unix_nano",
    "end_time_unix_nano",
    "attributes",
    "status",
}


def make_tracer() -> Tracer:
    ticks = itertools.count()
    ids = itertools.count(1)

    def clock() -> int:
        return next(ticks) * 1000

    def new_id(nbytes: int) -> str:
        return format(next(ids), "x").zfill(2 * nbytes)

    return Tracer(clock=clock, new_id=new_id)


def test_nested_spans_ids_parents_and_times():
    tracer = make_tracer()
    with tracer.span("a"):
        with tracer.span("b"):
            pass
    b, a = tracer.spans
    assert (b["name"], a["name"]) == ("b", "a")
    assert a["trace_id"] == "0" * 31 + "1"
    assert b["trace_id"] == "0" * 31 + "1"
    assert a["span_id"] == "0000000000000002"
    assert b["span_id"] == "0000000000000003"
    assert b["parent_span_id"] == a["span_id"]
    assert a["parent_span_id"] is None
    assert (a["start_time_unix_nano"], a["end_time_unix_nano"]) == (0, 3000)
    assert (b["start_time_unix_nano"], b["end_time_unix_nano"]) == (1000, 2000)
    assert a["status"] == "OK"
    assert b["status"] == "OK"


def test_attributes_at_open_and_added_inside_block():
    tracer = make_tracer()
    with tracer.span("a", first=1) as attrs:
        attrs["second"] = 2
    assert tracer.spans[0]["attributes"] == {"first": 1, "second": 2}


def test_exception_is_recorded_and_propagates():
    tracer = make_tracer()
    with pytest.raises(ValueError):
        with tracer.span("boom"):
            raise ValueError("bad")
    (span,) = tracer.spans
    assert span["status"] == "ERROR"
    assert span["attributes"]["exception.type"] == "ValueError"
    assert isinstance(span["end_time_unix_nano"], int)
    assert span["end_time_unix_nano"] > span["start_time_unix_nano"]


def test_second_root_span_gets_a_new_trace_id():
    tracer = make_tracer()
    with tracer.span("first"):
        pass
    with tracer.span("second"):
        pass
    first, second = tracer.spans
    assert first["trace_id"] != second["trace_id"]
    assert second["parent_span_id"] is None


def test_to_jsonl_writes_one_line_per_span(tmp_path):
    tracer = make_tracer()
    with tracer.span("a"):
        with tracer.span("b"):
            pass
    path = tmp_path / "spans.jsonl"
    count = tracer.to_jsonl(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert count == 2
    assert len(lines) == count
    for line in lines:
        record = json.loads(line)
        assert isinstance(record, dict)
        assert set(record) == SPAN_KEYS


def test_default_ids_are_lowercase_hex_of_the_right_length():
    tracer = Tracer()
    with tracer.span("a"):
        with tracer.span("b"):
            pass
    for span in tracer.spans:
        assert re.fullmatch(r"[0-9a-f]{32}", span["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", span["span_id"])
        assert isinstance(span["start_time_unix_nano"], int)
