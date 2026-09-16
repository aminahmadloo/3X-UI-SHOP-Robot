from app.bot.tasks import system_health


def test_network_interval_defaults_to_selected_interval(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {"network_interval_seconds": 300},
    )
    assert system_health._network_settings() == (False, 300, 60)
    assert system_health._network_interval_seconds() == 300


def test_network_interval_options_are_real_scheduler_intervals(monkeypatch):
    for seconds in (30, 300, 1800, 3600):
        monkeypatch.setattr(
            system_health,
            "load_health_settings",
            lambda seconds=seconds: {"network_interval_seconds": seconds},
        )
        assert system_health._network_interval_seconds() == seconds


def test_adaptive_monitoring_is_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {
            "network_interval_seconds": 1800,
            "network_adaptive_enabled": True,
            "network_incident_interval_seconds": 60,
        },
    )
    monkeypatch.setattr(
        system_health,
        "_load_state",
        lambda: {"current": "critical", "alert_level": "critical"},
    )
    assert system_health._network_interval_seconds() == 60


def test_adaptive_mode_disabled_keeps_selected_interval_during_incident(monkeypatch):
    monkeypatch.setattr(
        system_health,
        "load_health_settings",
        lambda: {
            "network_interval_seconds": 1800,
            "network_adaptive_enabled": False,
            "network_incident_interval_seconds": 60,
        },
    )
    monkeypatch.setattr(
        system_health,
        "_load_state",
        lambda: {"current": "critical", "alert_level": "critical"},
    )
    assert system_health._network_interval_seconds() == 1800
