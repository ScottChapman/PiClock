"""Staleness reporting and wedged-client recovery in the DataStore.

Both exist because of a failure mode seen in production: the process's
resolver wedges, every fetch then fails instantly with EAI_AGAIN, and
nothing recovers until a restart. See display/data.py.
"""

import dataclasses
from datetime import datetime, timedelta

import pytest

from display import data as data_mod


@pytest.fixture
def store():
    s = data_mod.DataStore()
    # Pin the interval so the thresholds below don't depend on Config.py.
    # Threshold is 2 missed cycles = 60 minutes.
    s.settings = dataclasses.replace(s.settings, weather_refresh_minutes=30)
    return s


def _age(store, **kw):
    """Pretend the last good fetch happened this long ago."""
    store.weather_updated = datetime.now() - timedelta(**kw)


def test_fresh_data_is_not_stale(store):
    _age(store, minutes=5)
    assert store.weather_staleness() is None


def test_one_missed_cycle_is_not_stale(store):
    # A single transient failure must not trip the warning.
    _age(store, minutes=45)
    assert store.weather_staleness() is None


def test_two_missed_cycles_is_stale(store):
    _age(store, minutes=75)
    stale = store.weather_staleness()
    assert stale is not None
    assert stale.last_update == store.weather_updated
    assert timedelta(minutes=74) < stale.age < timedelta(minutes=76)


def test_never_updated_reports_no_last_update(store):
    # The boot-race case: no network at startup, so we never had data at all.
    store.started = datetime.now() - timedelta(hours=3)
    assert store.weather_updated is None
    stale = store.weather_staleness()
    assert stale is not None
    assert stale.last_update is None


def test_startup_grace_before_first_fetch(store):
    # Fresh process with no data yet shouldn't warn immediately.
    assert store.weather_staleness() is None


async def test_each_refresh_builds_its_own_client(store, monkeypatch):
    # No connection pool may outlive a single refresh: pooled connections are
    # long expired between cycles anyway, and a wedged one must not persist.
    seen = []

    async def fake_fetch(settings, client):
        seen.append(client)
        return "weather"

    monkeypatch.setattr(data_mod.weather_module, "fetch", fake_fetch)
    await store.refresh_weather()
    await store.refresh_weather()

    assert len(seen) == 2
    assert seen[0] is not seen[1]
    assert all(c.is_closed for c in seen), "each client must be closed after its cycle"


async def test_client_is_closed_even_when_the_fetch_fails(store, monkeypatch):
    seen = []

    async def boom(settings, client):
        seen.append(client)
        raise RuntimeError("no network")

    monkeypatch.setattr(data_mod.weather_module, "fetch", boom)
    await store.refresh_weather()

    assert seen and seen[0].is_closed
    assert store.weather_updated is None


async def test_failure_count_tracks_runs_of_failures(store, monkeypatch):
    # The count is what tells a blip apart from a wedge in the log.
    async def boom(settings, client):
        raise RuntimeError("no network")

    async def ok(settings, client):
        return "weather"

    monkeypatch.setattr(data_mod.weather_module, "fetch", boom)
    await store.refresh_weather()
    await store.refresh_weather()
    assert store._failures == 2

    monkeypatch.setattr(data_mod.weather_module, "fetch", ok)
    await store.refresh_weather()
    assert store._failures == 0
