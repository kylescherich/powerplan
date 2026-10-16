"""Model-level tests for per-hour power commitments on a Site."""

from powerplan.models import Fleet, Site


def make_site(**overrides) -> Site:
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
    site = make_site()
    assert site.committed_kw_by_hour == [0.0] * 24


def test_new_sites_do_not_share_the_list():
    a = make_site(site_id="a")
    b = make_site(site_id="b")
    a.committed_kw_by_hour[3] = 50.0
    assert b.committed_kw_by_hour == [0.0] * 24


def test_headroom_at_hour_with_no_commitment():
    site = make_site()
    assert site.headroom_kw_at(0) == 800.0
    assert site.headroom_kw_at(13) == 800.0


def test_headroom_at_hour_subtracts_that_hours_commitment():
    site = make_site()
    site.committed_kw_by_hour[5] = 300.0
    assert site.headroom_kw_at(5) == 500.0
    assert site.headroom_kw_at(4) == 800.0
    assert site.headroom_kw_at(6) == 800.0


def test_headroom_at_hour_wraps():
    site = make_site()
    site.committed_kw_by_hour[1] = 100.0
    assert site.headroom_kw_at(25) == site.headroom_kw_at(1) == 700.0
    assert site.headroom_kw_at(24) == site.headroom_kw_at(0)


def test_headroom_at_hour_is_zero_when_offline():
    site = make_site(online=False)
    assert site.headroom_kw_at(0) == 0.0
    assert site.headroom_kw_at(25) == 0.0


def test_fleet_reset_zeroes_hourly_commitments():
    site = make_site()
    site.committed_kw_by_hour[2] = 120.0
    site.committed_kw_by_hour[23] = 40.0
    fleet = Fleet(sites=[site])
    fleet.reset()
    assert site.committed_kw_by_hour == [0.0] * 24
    assert len(site.committed_kw_by_hour) == 24
    assert site.headroom_kw_at(2) == 800.0
