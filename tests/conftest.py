import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


class FakeResponse:
    """Stand-in for requests.Response — just enough for the publisher code."""

    def __init__(self, status=200, json_data=None, headers=None, content=b""):
        self.status_code = status
        self.ok = status < 400
        self.content = content
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} Client Error")
