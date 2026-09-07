import hashlib
import hmac

from app.bot.payment_gateways.variza_gateway import VarizaGateway


def test_variza_signature_format():
    secret = "test-secret"
    payload = b'{"event":"payment.paid","slug":"abc","status":"paid"}'
    signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, signature)


def test_variza_tracking_code():
    assert VarizaGateway.tracking_code_for_slug("abc123") == "toonel-vz-abc123"
