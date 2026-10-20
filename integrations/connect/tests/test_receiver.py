import json
import time
from pathlib import Path

from integrations.connect import lambda_start, receiver

SECRET = "s3cret"


def signed(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    return body, lambda_start.sign(body, SECRET)


def test_check_accepts_signed_fresh_notification():
    body, sig = signed({"contactId": "c-1", "streamArn": "arn:x", "sentAt": int(time.time() * 1000)})
    status, payload = receiver.check(body, sig, SECRET)
    assert status == 202
    assert payload["contactId"] == "c-1"


def test_check_rejects_bad_signature_and_missing_stream():
    body, sig = signed({"contactId": "c-1", "streamArn": "arn:x", "sentAt": int(time.time() * 1000)})
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert receiver.check(body, tampered, SECRET)[0] == 401
    body, sig = signed({"contactId": "c-1", "sentAt": int(time.time() * 1000)})
    assert receiver.check(body, sig, SECRET)[0] == 400


def test_dump_command():
    cmd = receiver.dump_command({"contactId": "../c 1", "streamArn": "arn:x", "startFragment": "913"}, Path("out"), profile="p")
    assert cmd[1:3] == ["-m", "integrations.connect.kvs_dump"]
    assert cmd[cmd.index("--start-fragment") + 1] == "913"
    assert cmd[cmd.index("--contact-id") + 1] == "../c 1"
    assert Path(cmd[cmd.index("--out") + 1]) == Path("out") / "c_1"  # contact ID never escapes the output root
    assert cmd[-2:] == ["--profile", "p"]
