"""Shared Web UI session authentication."""
from __future__ import annotations

import hmac
import html
import os
from collections.abc import Awaitable, Callable
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

_TRUTHY = {"1", "true", "yes", "on"}
_PUBLIC_PATHS = {"/health", "/login", "/logout", "/favicon.ico"}
_SESSION_USER_KEY = "web_user"


def web_auth_enabled() -> bool:
    return os.environ.get("WEB_AUTH_ENABLED", "0").strip().lower() in _TRUTHY


def web_username() -> str:
    return os.environ.get("WEB_USERNAME", "admin").strip() or "admin"


def web_password() -> str:
    return os.environ.get("WEB_PASSWORD", "").strip()


def web_session_secret() -> str:
    return os.environ.get("WEB_SESSION_SECRET", "").strip() or "change_me_to_a_long_random_session_secret"


def web_session_cookie_name() -> str:
    return os.environ.get("WEB_SESSION_COOKIE", "semantic_sandbox_session").strip() or "semantic_sandbox_session"


def web_session_max_age_seconds() -> int:
    raw = os.environ.get("WEB_SESSION_MAX_AGE_SECONDS", "86400").strip()
    try:
        return max(int(raw), 300)
    except ValueError:
        return 86400


def web_session_https_only() -> bool:
    return os.environ.get("WEB_SESSION_HTTPS_ONLY", "0").strip().lower() in _TRUTHY


def _path_with_query(request: Request) -> str:
    path = request.url.path or "/"
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path


def _safe_next_path(raw: str | None) -> str:
    value = (raw or "/").strip() or "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _is_public_request(request: Request) -> bool:
    path = request.url.path
    return path in _PUBLIC_PATHS or path.startswith("/api/")


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get(_SESSION_USER_KEY))


def _login_page(*, next_path: str, error: str = "") -> str:
    escaped_next = html.escape(next_path, quote=True)
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Semantic Sandbox Login</title>
  <style>
    :root {{
      --bg: #050709;
      --panel: rgba(255, 255, 255, 0.055);
      --line: rgba(255, 255, 255, 0.11);
      --text: #f5f7fa;
      --muted: #a8b2bf;
      --brand: #1de5a1;
      --danger: #ff6b6b;
      --font: "Inter", "Avenir Next", "SF Pro Display", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ color-scheme: dark; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      color: var(--text);
      font-family: var(--font);
      background:
        radial-gradient(circle at top left, rgba(29, 229, 161, 0.15), transparent 32%),
        linear-gradient(180deg, #06080b 0%, #0b0f13 100%);
    }}
    main {{
      width: min(100%, 420px);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 28px;
      background: var(--panel);
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.36);
      backdrop-filter: blur(18px);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    p {{
      margin: 0 0 22px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    label {{
      display: grid;
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      color: var(--text);
      background: rgba(0, 0, 0, 0.28);
      font: inherit;
    }}
    button {{
      width: 100%;
      margin-top: 22px;
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      color: #04110c;
      background: var(--brand);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .error {{
      margin: 14px 0 0;
      color: var(--danger);
    }}
  </style>
</head>
<body>
  <main>
    <h1>Semantic Sandbox</h1>
    <p>请输入 Web UI 账号密码。</p>
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{escaped_next}">
      <label>用户名
        <input name="username" autocomplete="username" required autofocus>
      </label>
      <label>密码
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">登录</button>
      {error_html}
    </form>
  </main>
</body>
</html>"""


def install_web_login_auth(app: FastAPI) -> None:
    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request):
        next_path = _safe_next_path(request.query_params.get("next"))
        if not web_auth_enabled() or _is_authenticated(request):
            return RedirectResponse(next_path, status_code=303)
        return HTMLResponse(_login_page(next_path=next_path))

    @app.post("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_submit(request: Request):
        next_path = "/"
        try:
            form = await request.form()
            username = str(form.get("username", ""))
            password = str(form.get("password", ""))
            next_path = _safe_next_path(str(form.get("next", "/")))
        except Exception:
            return HTMLResponse(_login_page(next_path="/", error="登录请求无效"), status_code=400)

        expected_password = web_password()
        if not web_auth_enabled():
            return RedirectResponse(next_path, status_code=303)
        if not expected_password:
            return HTMLResponse(_login_page(next_path=next_path, error="服务端未配置 WEB_PASSWORD"), status_code=500)
        if not hmac.compare_digest(username, web_username()) or not hmac.compare_digest(password, expected_password):
            return HTMLResponse(_login_page(next_path=next_path, error="用户名或密码错误"), status_code=401)

        request.session[_SESSION_USER_KEY] = username
        return RedirectResponse(next_path, status_code=303)

    @app.api_route("/logout", methods=["GET", "POST"], include_in_schema=False)
    async def logout(request: Request):
        request.session.clear()
        target = "/login" if web_auth_enabled() else "/"
        return RedirectResponse(target, status_code=303)

    @app.middleware("http")
    async def web_login_auth(request: Request, call_next: Callable[[Request], Awaitable]):
        if not web_auth_enabled() or _is_public_request(request) or _is_authenticated(request):
            return await call_next(request)
        next_path = quote(_path_with_query(request), safe="")
        return RedirectResponse(f"/login?next={next_path}", status_code=303)

    app.add_middleware(
        SessionMiddleware,
        secret_key=web_session_secret(),
        session_cookie=web_session_cookie_name(),
        max_age=web_session_max_age_seconds(),
        same_site="lax",
        https_only=web_session_https_only(),
    )
