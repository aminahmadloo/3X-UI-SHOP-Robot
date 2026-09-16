from app.bot.tasks import system_health


def test_selected_interval_remains_effective_during_incident(monkeypatch):
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
