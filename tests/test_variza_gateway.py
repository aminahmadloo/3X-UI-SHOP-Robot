import hashlib
import hmac

from app.bot.payment_gateways.variza_gateway import VarizaGateway


def test_variza_signature_accepts_valid_payload(monkeypatch):
    secret = "test-secret"
    payload = b'{"event":"payment.paid","slug":"abc","status":"paid"}'
    monkeypatch.setenv("VARIZA_WEBHOOK_SECRET", secret)
    signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    assert VarizaGateway._valid_signature(payload, signature) is True


def test_variza_signature_rejects_tampered_payload(monkeypatch):
    secret = "test-secret"
    payload = b'{"event":"payment.paid","slug":"abc","status":"paid"}'
    monkeypatch.setenv("VARIZA_WEBHOOK_SECRET", secret)
    signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    assert VarizaGateway._valid_signature(payload + b"x", signature) is False


def test_variza_signature_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("VARIZA_WEBHOOK_SECRET", raising=False)
    assert VarizaGateway._valid_signature(b"{}", "sha256=anything") is False


def test_variza_tracking_code():
    assert VarizaGateway.tracking_code_for_slug("abc123") == "toonel-vz-abc123"


def test_variza_accepts_documented_expiry_values(monkeypatch):
    for value in ("30m", "1h", "2h", "6h", "1d", "1w", "never"):
        monkeypatch.setenv("VARIZA_EXPIRES_IN", value)
        assert VarizaGateway._expires_in() == value
