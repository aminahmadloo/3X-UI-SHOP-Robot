from __future__ import annotations

import json

from app.bot.services import network_health


def _report(severity: str) -> dict:
    return {
        "timestamp": 1,
        "ping_count": 5,
        "servers": [
            {
                "id": 1,
                "name": "test",
                "endpoint": {
                    "severity": severity,
                    "avg_ms": 10 if severity == "healthy" else 500,
                    "loss_percent": 0 if severity == "healthy" else 100,
                },
                "public": {
                    "severity": severity,
                    "avg_ms": 10 if severity == "healthy" else 500,
                    "loss_percent": 0 if severity == "healthy" else 100,
                },
                "nodes": [],
            }
        ],
    }


def test_three_failures_alert_once_fourth_failure_no_duplicate(monkeypatch, tmp_path):
    state_path = tmp_path / "network_health_history.json"
    monkeypatch.setattr(network_health, "HISTORY_PATHS", (state_path,))

    assert network_health.update_alert_state(_report("healthy"))[0] is None
    assert network_health.update_alert_state(_report("critical"))[0] is None
    assert network_health.update_alert_state(_report("critical"))[0] is None
    assert network_health.update_alert_state(_report("critical"))[0] == "degraded"
    assert network_health.update_alert_state(_report("critical"))[0] is None

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["alert_level"] == "critical"
    assert state["bad_count"] == 5


def test_recovery_requires_two_healthy_samples(monkeypatch, tmp_path):
    state_path = tmp_path / "network_health_history.json"
    monkeypatch.setattr(network_health, "HISTORY_PATHS", (state_path,))

    network_health.update_alert_state(_report("critical"))
    network_health.update_alert_state(_report("critical"))
    assert network_health.update_alert_state(_report("critical"))[0] == "degraded"

    assert network_health.update_alert_state(_report("healthy"))[0] is None
    assert network_health.update_alert_state(_report("healthy"))[0] == "recovered"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["alert_level"] == "healthy"
    assert state["good_count"] == 2


def test_second_incident_produces_new_alert_after_recovery(monkeypatch, tmp_path):
    state_path = tmp_path / "network_health_history.json"
    monkeypatch.setattr(network_health, "HISTORY_PATHS", (state_path,))

    for _ in range(3):
        alert, _ = network_health.update_alert_state(_report("problem"))
    assert alert == "degraded"

    network_health.update_alert_state(_report("healthy"))
    assert network_health.update_alert_state(_report("healthy"))[0] == "recovered"

    for _ in range(2):
        network_health.update_alert_state(_report("problem"))
    assert network_health.update_alert_state(_report("problem"))[0] == "degraded"


def test_bad_sample_resets_good_counter_and_healthy_sample_resets_bad_counter(monkeypatch, tmp_path):
    state_path = tmp_path / "network_health_history.json"
    monkeypatch.setattr(network_health, "HISTORY_PATHS", (state_path,))

    network_health.update_alert_state(_report("healthy"))
    network_health.update_alert_state(_report("critical"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["good_count"] == 0
    assert state["bad_count"] == 1

    network_health.update_alert_state(_report("healthy"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["bad_count"] == 0
    assert state["good_count"] == 1
