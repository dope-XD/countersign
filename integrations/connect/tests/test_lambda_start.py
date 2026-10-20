import hashlib
import hmac
import json
import urllib.error

import pytest

from integrations.connect import lambda_start

SECRET = "test-shared-secret"

EVENT = {
    "Name": "ContactFlowEvent",
    "Details": {
        "ContactData": {
            "Attributes": {"bank": "demo", "lang": "hi-IN"},
            "Channel": "VOICE",
            "ContactId": "4a573372-1f28-4e26-b97b-000000000001",
            "InitialContactId": "4a573372-1f28-4e26-b97b-000000000001",
            "InstanceARN": "arn:aws:connect:ap-southeast-1:111111111111:instance/c8c0e68d-2200-4265-82c0-000000000000",
            "CustomerEndpoint": {"Address": "+911234567890", "Type": "TELEPHONE_NUMBER"},
            "MediaStreams": {
                "Customer": {
                    "Audio": {
                        "StreamARN": "arn:aws:kinesisvideo:ap-southeast-1:111111111111:stream/countersign-contact-abc/1700000000000",
                        "StartTimestamp": "1571360125131",
                        "StartFragmentNumber": "91343852333181432392682062606740271849390003051",
                    }
                }
            },
        },
        "Parameters": {},
    },
}


def test_sign_matches_reference_hmac():
    body = b'{"contactId":"x"}'
    expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert lambda_start.sign(body, SECRET) == "sha256=" + expected
    assert lambda_start.sign(body, SECRET.encode()) == "sha256=" + expected
    assert lambda_start.sign(body + b" ", SECRET) != "sha256=" + expected  # any byte change breaks it
    assert lambda_start.sign(body, "other") != "sha256=" + expected


def test_verify_checks_signature_and_freshness():
    body = json.dumps({"contactId": "x", "sentAt": 1_000_000}).encode()
    good = lambda_start.sign(body, SECRET)
    assert lambda_start.verify(body, good, SECRET, now_ms=1_000_500)
    assert not lambda_start.verify(body, good, SECRET, now_ms=1_000_000 + lambda_start.MAX_SKEW_MS + 1)  # replayed later
    assert not lambda_start.verify(body, good, "wrong", now_ms=1_000_500)
    assert not lambda_start.verify(body, None, SECRET, now_ms=1_000_500)
    unsigned_time = json.dumps({"contactId": "x"}).encode()
    assert not lambda_start.verify(unsigned_time, lambda_start.sign(unsigned_time, SECRET), SECRET)


def test_build_payload_reads_connect_event():
    p = lambda_start.build_payload(EVENT, now_ms=42)
    assert p == {
        "contactId": "4a573372-1f28-4e26-b97b-000000000001",
        "initialContactId": "4a573372-1f28-4e26-b97b-000000000001",
        "instanceArn": EVENT["Details"]["ContactData"]["InstanceARN"],
        "streamArn": "arn:aws:kinesisvideo:ap-southeast-1:111111111111:stream/countersign-contact-abc/1700000000000",
        "startFragment": "91343852333181432392682062606740271849390003051",
        "startTimestamp": "1571360125131",
        "attributes": {"bank": "demo", "lang": "hi-IN"},
        "sentAt": 42,
    }
    assert "+911234567890" not in json.dumps(p)  # caller number stays out unless the flow puts it in an attribute


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ENGINE_URL", "https://engine.example.test/")
    monkeypatch.setenv("CONNECT_HMAC_SECRET", SECRET)


class FakeResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_handler_posts_signed_body(env, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, body=req.data, headers=dict(req.header_items()), timeout=timeout, method=req.get_method())
        return FakeResponse()

    monkeypatch.setattr(lambda_start.urllib.request, "urlopen", fake_urlopen)
    assert lambda_start.handler(EVENT) == {"countersign": "ok", "status": "http_202"}

    assert seen["url"] == "https://engine.example.test/api/ingest/connect/start"
    assert seen["method"] == "POST"
    assert seen["timeout"] == lambda_start.DEFAULT_TIMEOUT_S
    sig = seen["headers"]["X-countersign-signature"]  # urllib capitalises header names
    assert sig == lambda_start.sign(seen["body"], SECRET)
    assert lambda_start.verify(seen["body"], sig, SECRET)
    body = json.loads(seen["body"])
    assert body["streamArn"].endswith("/1700000000000")
    assert body["startFragment"] == "91343852333181432392682062606740271849390003051"


def test_handler_without_stream_does_not_post(env, monkeypatch):
    monkeypatch.setattr(lambda_start.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not POST"))
    event = json.loads(json.dumps(EVENT))
    del event["Details"]["ContactData"]["MediaStreams"]
    assert lambda_start.handler(event) == {"countersign": "no_stream"}


def test_handler_not_configured(monkeypatch):
    monkeypatch.delenv("ENGINE_URL", raising=False)
    monkeypatch.delenv("CONNECT_HMAC_SECRET", raising=False)
    assert lambda_start.handler(EVENT) == {"countersign": "not_configured"}


@pytest.mark.parametrize(
    "exc, status",
    [
        (urllib.error.HTTPError("u", 401, "bad sig", {}, None), "http_401"),
        (urllib.error.URLError("dns"), "unreachable"),
        (TimeoutError("slow"), "unreachable"),
    ],
    ids=["http_error", "url_error", "timeout"],
)
def test_handler_never_raises(env, monkeypatch, exc, status):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(lambda_start.urllib.request, "urlopen", boom)
    result = lambda_start.handler(EVENT)
    assert result == {"countersign": "error", "status": status}
    assert all(c.isalnum() or c in "-_" for v in result.values() for c in v)  # Connect's allowed characters
