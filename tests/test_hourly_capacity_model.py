"""Model-level tests for hour-indexed power commitments."""

from powerplan.models import Fleet, Site


def _site(**overrides) -> Site:
    params = dict(
        site_id="s1",
        region="us-east",
        power_capacity_kw=1000.0,
        baseline_load_kw=200.0,
        pue=1.2,
        price_per_kwh=0.10,
        carbon_g_per_kwh=400.0,
    )
    params.update(overrides)
    return Site(**params)


def test_new_site_has_24_zeros():
    site = _site()
    assert site.committed_kw_by_hour == [0.0] * 24


def test_new_sites_do_not_share_the_list():
    a = _site(site_id="a")
    b = _site(site_id="b")
    a.committed_kw_by_hour[3] = 50.0
    assert b.committed_kw_by_hour == [0.0] * 24


def test_headroom_kw_at_subtracts_that_hours_commitment():
    site = _site()
    site.committed_kw_by_hour[5] = 150.0
    assert site.headroom_kw_at(5) == 1000.0 - 200.0 - 150.0
    assert site.headroom_kw_at(6) == 1000.0 - 200.0


def test_headroom_kw_at_wraps_hour():
    site = _site()
    site.committed_kw_by_hour[1] = 100.0
    assert site.headroom_kw_at(25) == 1000.0 - 200.0 - 100.0
    assert site.headroom_kw_at(25) == site.headroom_kw_at(1)


def test_headroom_kw_at_is_zero_when_offline():
    site = _site()
    site.committed_kw_by_hour[2] = 10.0
    site.online = False
    assert site.headroom_kw_at(2) == 0.0
    assert site.headroom_kw_at(0) == 0.0


def test_fleet_reset_zeroes_hourly_commitments():
    site = _site()
    fleet = Fleet(sites=[site])
    site.committed_kw = 75.0
    site.committed_kw_by_hour[0] = 75.0
    site.committed_kw_by_hour[23] = 40.0

    fleet.reset()

    assert site.committed_kw == 0.0
    assert site.committed_kw_by_hour == [0.0] * 24
    assert len(site.committed_kw_by_hour) == 24
