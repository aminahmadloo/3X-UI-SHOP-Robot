from app.bot.services import network_health
from app.bot.tasks import system_health


def test_network_interval_defaults_to_persisted_selected_interval(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {"network_interval_seconds": 300},
    )
    monkeypatch.setattr(system_health, "_load_state", lambda: {"current": "healthy", "alert_level": "healthy"})
    assert system_health._network_settings() == (True, 300, 60)
    assert system_health._network_interval_seconds() == 300


def test_network_interval_options_are_real_scheduler_intervals(monkeypatch):
    for seconds in (30, 300, 1800, 3600):
        monkeypatch.setattr(
            system_health,
            "load_health_settings",
            lambda seconds=seconds: {"network_interval_seconds": seconds},
        )
        monkeypatch.setattr(system_health, "_load_state", lambda: {"current": "healthy", "alert_level": "healthy"})
        assert system_health._network_interval_seconds() == seconds


def test_adaptive_monitoring_uses_fixed_60_seconds_during_incident(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {"network_interval_seconds": 1800},
    )
    monkeypatch.setattr(
        system_health,
        "_load_state",
        lambda: {"current": "critical", "alert_level": "critical"},
    )
    assert system_health._network_settings() == (True, 1800, 60)
    assert system_health._network_interval_seconds() == 60


def test_persisted_selected_interval_returns_after_recovery(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {"network_interval_seconds": 1800},
    )
    states = iter(
        [
            {"current": "critical", "alert_level": "critical"},
            {"current": "healthy", "alert_level": "healthy"},
        ]
    )
    monkeypatch.setattr(system_health, "_load_state", lambda: next(states))
    assert system_health._network_interval_seconds() == 60
    assert system_health._network_interval_seconds() == 1800


def test_three_consecutive_incident_samples_trigger_one_degraded_alert(monkeypatch):
    state = {"current": "healthy", "alert_level": "healthy", "bad_count": 0, "good_count": 0, "history": []}
    saved = []

    monkeypatch.setattr(network_health, "_load_state", lambda: dict(state))
    monkeypatch.setattr(network_health, "_save_state", lambda value: (state.clear(), state.update(value), saved.append(value))[2])

    report = {"timestamp": 1, "servers": [{"name": "test", "endpoint": {"severity": "warning"}, "public": {"severity": "healthy"}, "nodes": []}], "ping_count": 5}
    assert network_health.update_alert_state(report)[0] is None
    assert network_health.update_alert_state(report)[0] is None
    assert network_health.update_alert_state(report)[0] == "degraded"
    assert state["bad_count"] == 3
    assert state["alert_level"] == "warning"


def test_recovery_resets_incident_state_and_allows_future_alert(monkeypatch):
    state = {"current": "warning", "alert_level": "warning", "bad_count": 4, "good_count": 0, "history": []}
    monkeypatch.setattr(network_health, "_load_state", lambda: dict(state))
    monkeypatch.setattr(network_health, "_save_state", lambda value: (state.clear(), state.update(value)))

    healthy = {"timestamp": 2, "servers": [{"name": "test", "endpoint": {"severity": "healthy"}, "public": {"severity": "healthy"}, "nodes": []}], "ping_count": 5}
    assert network_health.update_alert_state(healthy)[0] is None
    assert network_health.update_alert_state(healthy)[0] == "recovered"
    assert state["alert_level"] == "healthy"
    assert state["bad_count"] == 0
    assert state["good_count"] == 2
