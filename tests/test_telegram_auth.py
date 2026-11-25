import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from aiohttp import web

from app.webapp_server import _telegram_user


TOKEN = "unit-test-token"


class FakeRequest:
    def __init__(self, init_data):
        self.headers = {"Authorization": "Bearer " + init_data}


def signed_data(user=None, auth_date=None):
    pairs = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "user": json.dumps(user or {"id": 12345, "first_name": "Test"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


class TelegramAuthTests(unittest.TestCase):
    def test_valid_signature(self):
        self.assertEqual(_telegram_user(FakeRequest(signed_data()), TOKEN)["id"], 12345)

    def test_tampered_data_rejected(self):
        data = signed_data().replace("Test", "Tampered")
        with self.assertRaises(web.HTTPUnauthorized):
            _telegram_user(FakeRequest(data), TOKEN)

    def test_expired_data_rejected(self):
        data = signed_data(auth_date=int(time.time()) - 86401)
        with self.assertRaises(web.HTTPUnauthorized):
            _telegram_user(FakeRequest(data), TOKEN)

    def test_duplicate_keys_rejected(self):\n        data = signed_data() + "&auth_date=" + str(int(time.time()))\n        with self.assertRaises(web.HTTPUnauthorized):\n            _telegram_user(FakeRequest(data), TOKEN)\n\n    def test_future_auth_date_rejected(self):\n        data = signed_data(auth_date=int(time.time()) + 120)\n        with self.assertRaises(web.HTTPUnauthorized):\n            _telegram_user(FakeRequest(data), TOKEN)\n\n    def test_missing_authorization_rejected(self):
        request = FakeRequest("")
        request.headers = {}
        with self.assertRaises(web.HTTPUnauthorized):
            _telegram_user(request, TOKEN)


if __name__ == "__main__":
    unittest.main()
