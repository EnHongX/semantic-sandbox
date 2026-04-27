import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from semantic_sandbox_web_auth import install_web_login_auth


class WebLoginAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {
            key: os.environ.get(key)
            for key in (
                "WEB_AUTH_ENABLED",
                "WEB_USERNAME",
                "WEB_PASSWORD",
                "WEB_SESSION_SECRET",
                "WEB_SESSION_COOKIE",
                "WEB_SESSION_MAX_AGE_SECONDS",
                "WEB_SESSION_HTTPS_ONLY",
            )
        }

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _client(self) -> TestClient:
        app = FastAPI()
        install_web_login_auth(app)

        @app.get("/")
        async def home():
            return {"ok": True}

        @app.get("/health")
        async def health():
            return {"ok": True}

        @app.get("/api/private")
        async def private():
            return {"ok": True}

        return TestClient(app)

    def _enable_auth(self) -> None:
        os.environ["WEB_AUTH_ENABLED"] = "1"
        os.environ["WEB_USERNAME"] = "admin"
        os.environ["WEB_PASSWORD"] = "secret"
        os.environ["WEB_SESSION_SECRET"] = "test-session-secret"

    def test_auth_disabled_allows_web_pages(self) -> None:
        os.environ["WEB_AUTH_ENABLED"] = "0"

        res = self._client().get("/")

        self.assertEqual(res.status_code, 200)

    def test_health_stays_public_when_auth_enabled(self) -> None:
        self._enable_auth()

        res = self._client().get("/health")

        self.assertEqual(res.status_code, 200)

    def test_api_paths_are_left_to_api_key_auth(self) -> None:
        self._enable_auth()

        res = self._client().get("/api/private")

        self.assertEqual(res.status_code, 200)

    def test_web_page_redirects_to_login_when_unauthenticated(self) -> None:
        self._enable_auth()

        res = self._client().get("/", follow_redirects=False)

        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/login?next=%2F")

    def test_swagger_ui_is_protected_by_web_login(self) -> None:
        self._enable_auth()

        res = self._client().get("/docs", follow_redirects=False)

        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/login?next=%2Fdocs")

    def test_login_rejects_bad_credentials(self) -> None:
        self._enable_auth()

        res = self._client().post(
            "/login",
            data={"username": "admin", "password": "wrong", "next": "/"},
            follow_redirects=False,
        )

        self.assertEqual(res.status_code, 401)

    def test_login_sets_session_cookie_and_allows_next_request(self) -> None:
        self._enable_auth()
        client = self._client()

        login = client.post(
            "/login",
            data={"username": "admin", "password": "secret", "next": "/"},
            follow_redirects=False,
        )
        home = client.get("/")

        self.assertEqual(login.status_code, 303)
        self.assertIn("semantic_sandbox_session=", login.headers["set-cookie"])
        self.assertEqual(home.status_code, 200)

    def test_logout_clears_session(self) -> None:
        self._enable_auth()
        client = self._client()
        client.post(
            "/login",
            data={"username": "admin", "password": "secret", "next": "/"},
            follow_redirects=False,
        )

        logout = client.get("/logout", follow_redirects=False)
        home = client.get("/", follow_redirects=False)

        self.assertEqual(logout.status_code, 303)
        self.assertEqual(logout.headers["location"], "/login")
        self.assertEqual(home.status_code, 303)

    def test_open_redirect_next_is_rejected(self) -> None:
        self._enable_auth()

        res = self._client().post(
            "/login",
            data={"username": "admin", "password": "secret", "next": "https://example.com"},
            follow_redirects=False,
        )

        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/")


if __name__ == "__main__":
    unittest.main()
