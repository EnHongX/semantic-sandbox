import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from semantic_sandbox_auth import install_api_key_auth


class ApiKeyAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {
            key: os.environ.get(key)
            for key in ("AUTH_ENABLED", "API_KEY", "API_KEY_HEADER")
        }

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _client(self) -> TestClient:
        app = FastAPI()
        install_api_key_auth(app)

        @app.get("/health")
        async def health():
            return {"ok": True}

        @app.get("/api/private")
        async def private():
            return {"ok": True}

        @app.get("/api/count")
        async def count():
            return {"count": 0}

        return TestClient(app)

    def test_auth_disabled_allows_api_requests(self) -> None:
        os.environ["AUTH_ENABLED"] = "0"
        os.environ["API_KEY"] = "secret"

        res = self._client().get("/api/private")

        self.assertEqual(res.status_code, 200)

    def test_health_stays_public_when_auth_enabled(self) -> None:
        os.environ["AUTH_ENABLED"] = "1"
        os.environ["API_KEY"] = "secret"

        res = self._client().get("/health")

        self.assertEqual(res.status_code, 200)

    def test_missing_api_key_is_rejected(self) -> None:
        os.environ["AUTH_ENABLED"] = "1"
        os.environ["API_KEY"] = "secret"

        res = self._client().get("/api/private")

        self.assertEqual(res.status_code, 401)

    def test_public_browser_helper_api_stays_open(self) -> None:
        os.environ["AUTH_ENABLED"] = "1"
        os.environ["API_KEY"] = "secret"

        res = self._client().get("/api/count")

        self.assertEqual(res.status_code, 200)

    def test_valid_api_key_is_allowed(self) -> None:
        os.environ["AUTH_ENABLED"] = "1"
        os.environ["API_KEY"] = "secret"

        res = self._client().get("/api/private", headers={"X-API-Key": "secret"})

        self.assertEqual(res.status_code, 200)

    def test_custom_header_name_is_supported(self) -> None:
        os.environ["AUTH_ENABLED"] = "1"
        os.environ["API_KEY"] = "secret"
        os.environ["API_KEY_HEADER"] = "X-Service-Key"

        res = self._client().get("/api/private", headers={"X-Service-Key": "secret"})

        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
