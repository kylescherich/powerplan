from pathlib import Path

import pytest

from powerplan.models import load_fleet
from powerplan.telemetry import (
    POWER,
    apply_gpu_power,
    gpu_it_kw_by_site,
    parse_prometheus,
)

DATA = Path(__file__).resolve().parent.parent / "data"

# Same content as examples/telemetry/dcgm.prom
DCGM_TEXT = """# HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
# TYPE DCGM_FI_DEV_POWER_USAGE gauge
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000001",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 612.5
DCGM_FI_DEV_POWER_USAGE{gpu="1",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000002",device="nvidia1",modelName="NVIDIA H100 80GB HBM3",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 587.5
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000003",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",Hostname="or-node-07",site="SITE-OR",pool="or-h100"} 400 1792195200000
# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C).
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{gpu="0",UUID="GPU-0a1b2c3d-0000-0000-0000-000000000001",Hostname="tx-node-01",site="SITE-TX",pool="tx-h100"} 61
"""


def fresh_fleet():
    return load_fleet(DATA / "fleet.json")


def test_parse_prometheus_returns_the_four_samples():
    samples = parse_prometheus(DCGM_TEXT)
    assert len(samples) == 4

    names = [name for name, _, _ in samples]
    assert names == [POWER, POWER, POWER, "DCGM_FI_DEV_GPU_TEMP"]

    power = [(labels["site"], value) for name, labels, value in samples if name == POWER]
    assert power == [("SITE-TX", 612.5), ("SITE-TX", 587.5), ("SITE-OR", 400.0)]

    name, labels, value = samples[3]
    assert value == 61.0
    assert labels["site"] == "SITE-TX"
    assert labels["pool"] == "tx-h100"


def test_gpu_it_kw_by_site_sums_power_and_ignores_other_metrics():
    kw = gpu_it_kw_by_site(parse_prometheus(DCGM_TEXT))
    assert set(kw) == {"SITE-TX", "SITE-OR"}
    assert kw["SITE-TX"] == pytest.approx(1.2, abs=1e-9)
    assert kw["SITE-OR"] == pytest.approx(0.4, abs=1e-9)


def test_apply_gpu_power_adds_facility_kw_to_baseline():
    fleet = fresh_fleet()
    apply_gpu_power(fleet, gpu_it_kw_by_site(parse_prometheus(DCGM_TEXT)))
    assert fleet.site("SITE-TX").baseline_load_kw == pytest.approx(901.536, abs=1e-9)
    assert fleet.site("SITE-OR").baseline_load_kw == pytest.approx(500.46, abs=1e-9)
    assert fleet.site("SITE-EU").baseline_load_kw == 420


def test_label_value_escapes():
    text = r'm{a="x\"y",b="c\\d"} 1.5'
    [(name, labels, value)] = parse_prometheus(text)
    assert name == "m"
    assert labels == {"a": 'x"y', "b": "c\\d"}
    assert len(labels["b"]) == 3
    assert value == 1.5


def test_newline_escape_in_label_value():
    [(_, labels, _)] = parse_prometheus(r'm{a="x\ny"} 1')
    assert labels == {"a": "x\ny"}


def test_non_numeric_value_names_the_line():
    with pytest.raises(ValueError, match="line 1"):
        parse_prometheus('m{a="x"} notanumber')


def test_malformed_labels_name_the_line():
    with pytest.raises(ValueError, match="line 1"):
        parse_prometheus("m{a=x} 1")


def test_error_line_number_counts_skipped_lines():
    text = '# comment\n\nm{a="x"} 1\nm{a="x"} oops\n'
    with pytest.raises(ValueError, match="line 4"):
        parse_prometheus(text)


def test_power_sample_without_site_label_is_rejected():
    samples = parse_prometheus('DCGM_FI_DEV_POWER_USAGE{gpu="0"} 5')
    with pytest.raises(ValueError):
        gpu_it_kw_by_site(samples)


def test_non_finite_power_sample_is_rejected():
    samples = parse_prometheus('DCGM_FI_DEV_POWER_USAGE{site="SITE-TX"} NaN')
    with pytest.raises(ValueError):
        gpu_it_kw_by_site(samples)


def test_apply_gpu_power_unknown_site_names_it_and_changes_nothing():
    fleet = fresh_fleet()
    with pytest.raises(ValueError, match="SITE-XX"):
        apply_gpu_power(fleet, {"SITE-TX": 1.0, "SITE-XX": 1.0})
    assert fleet.site("SITE-TX").baseline_load_kw == 900
