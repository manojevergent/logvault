"""Auth: login, current user, user management (admin-only CRUD)."""

from __future__ import annotations

import contextlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import User
from app.redis_client import get_redis
from app.schemas import UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ALGORITHM = "HS256"
_TOKEN_TTL_HOURS = 24


def _hash(pw: str) -> str:
    return _pwd.hash(pw)


def _verify(pw: str, hashed: str) -> bool:
    return _pwd.verify(pw, hashed)


def _make_token(email: str, role: str) -> str:
    exp = datetime.now(UTC) + timedelta(hours=_TOKEN_TTL_HOURS)
    return jwt.encode(
        {"sub": email, "role": role, "exp": exp},
        get_settings().jwt_secret,
        algorithm=_ALGORITHM,
    )


def ensure_initial_admin(db: Session) -> None:
    """Create first admin from env vars if no users exist."""
    s = get_settings()
    if not s.initial_admin_email or not s.initial_admin_password:
        return
    if db.query(User).count() == 0:
        db.add(
            User(
                email=s.initial_admin_email,
                name="Admin",
                hashed_password=_hash(s.initial_admin_password),
                role="admin",
            )
        )
        db.commit()


def _fail_key(email: str) -> str:
    return f"login:fail:{email.strip().lower()}"


def _failed_attempts(key: str) -> int:
    """How many failures are on record. 0 when Redis is unreachable.

    Failing open is the deliberate choice: a broken throttle that locks every
    engineer out of the platform is a worse outage than the brute-force attempt
    it was guarding against, and these credentials front an internal tool.
    """
    try:
        return int(get_redis().get(key) or 0)
    except Exception:  # noqa: BLE001 - any Redis problem means "no record"
        return 0


def _record_failure(key: str, ttl_seconds: int) -> None:
    try:
        r = get_redis()
        # TTL set on the first failure only, so the window is fixed from that
        # point: further attempts cannot keep extending their own lockout.
        if r.incr(key) == 1:
            r.expire(key, ttl_seconds)
    except Exception:  # noqa: BLE001
        pass


def _clear_failures(key: str) -> None:
    with contextlib.suppress(Exception):
        get_redis().delete(key)


class LoginBody(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/login", response_model=TokenOut)
def login(body: LoginBody, db: Session = Depends(get_db)) -> TokenOut:
    ensure_initial_admin(db)
    s = get_settings()
    key = _fail_key(body.email)

    # Counted per email rather than per source address: the account is what is
    # under attack, and these sessions reach production Last9 credentials for
    # every region. ponytail: no IP dimension until one is actually needed.
    if _failed_attempts(key) >= s.login_max_attempts:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {s.login_lockout_seconds // 60} minutes.",
        )

    user = db.query(User).filter(User.email == body.email).first()
    # Google-only accounts have no password hash — reject outright instead of
    # letting passlib raise on a None hash (a 500 for a normal login attempt).
    if (
        user is None
        or user.hashed_password is None
        or not _verify(body.password, user.hashed_password)
    ):
        _record_failure(key, s.login_lockout_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _clear_failures(key)
    return TokenOut(access_token=_make_token(user.email, user.role), role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


# ── Google sign-in (OAuth authorization-code flow) ────────────────────────────
#
# Password login stays as-is; this is an additional door, advertised by
# /providers and hidden in the UI while unconfigured. The session it mints is
# the same 24h JWT every other endpoint already accepts, so nothing downstream
# changes.
#
# Handoff to the web app goes in the URL *fragment* (#access_token=...), never
# the query string: fragments never reach server or proxy logs (see signing.py
# for why secrets don't belong in logged URLs).

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
_STATE_TTL_SECONDS = 600
_STATE_COOKIE = "lv_oauth_state"


class ProvidersOut(BaseModel):
    password: bool = True
    google: bool = False


@router.get("/providers", response_model=ProvidersOut)
def auth_providers() -> ProvidersOut:
    return ProvidersOut(google=get_settings().google_enabled)


def _redirect_uri() -> str:
    # Must match an Authorized redirect URI in the Google Cloud console exactly.
    return get_settings().public_api_base.rstrip("/") + "/auth/google/callback"


def _web_base() -> str:
    return get_settings().web_base_url.rstrip("/") or "http://localhost:3001"


def _safe_next(raw: str | None) -> str:
    """Open-redirect guard: the post-login landing page must be an in-app path."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


def _fail_redirect(code: str, next_path: str) -> RedirectResponse:
    return RedirectResponse(
        f"{_web_base()}/login?error={quote(code, safe='')}&from={quote(next_path, safe='')}",
        status_code=302,
    )


def _mint_state(next_path: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "purpose": "oauth-state",
            "nonce": secrets.token_urlsafe(16),
            "next": next_path,
            "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        },
        get_settings().jwt_secret,
        algorithm=_ALGORITHM,
    )


@router.get("/google/login")
def google_login(next: str = "/") -> RedirectResponse:
    s = get_settings()
    if not s.google_enabled:
        return _fail_redirect("disabled", _safe_next(next))
    next_path = _safe_next(next)
    state = _mint_state(next_path)
    params = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    resp = RedirectResponse(f"{_GOOGLE_AUTH_URL}?{params}", status_code=302)
    # CSRF binding: the same signed state goes in a Lax cookie, so only the
    # browser that started the flow can finish it. Lax (not Strict) because
    # Google's redirect back here is a cross-site top-level navigation.
    resp.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=s.public_api_base.startswith("https://"),
    )
    return resp


def _read_state(state: str | None, cookie: str | None) -> str:
    """Verify the state round-trip; return the validated next path."""
    if not state or not cookie or not hmac.compare_digest(state, cookie):
        raise _OAuthFailure("invalid_state")
    try:
        claims = jwt.decode(state, get_settings().jwt_secret, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise _OAuthFailure("invalid_state") from exc
    if claims.get("purpose") != "oauth-state":
        raise _OAuthFailure("invalid_state")
    return _safe_next(claims.get("next"))


class _OAuthFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _exchange_code(code: str) -> dict:
    """Trade the authorization code for tokens. Raises _OAuthFailure."""
    s = get_settings()
    try:
        resp = httpx.Client(timeout=15.0).post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 - timeout, TLS, 4xx/5xx all mean "no token"
        raise _OAuthFailure("oauth_failed") from exc
    if not isinstance(body, dict) or not body.get("id_token"):
        raise _OAuthFailure("oauth_failed")
    return body


def _validate_id_token(id_token: str) -> dict:
    """Validate the ID token against Google and return its claims.

    Verification goes through Google's tokeninfo endpoint rather than local
    signature checks, so there is no cert cache to run or rotate — one extra
    round trip per login, which is nothing next to a human clicking through
    Google's consent screen.
    """
    s = get_settings()
    try:
        resp = httpx.Client(timeout=15.0).get(_GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
        resp.raise_for_status()
        info = resp.json()
    except Exception as exc:  # noqa: BLE001 - see _exchange_code
        raise _OAuthFailure("oauth_failed") from exc
    if not isinstance(info, dict):
        raise _OAuthFailure("oauth_failed")
    try:
        valid = (
            info.get("aud") == s.google_client_id
            and info.get("iss") in _GOOGLE_ISSUERS
            and str(info.get("email_verified", "")).lower() == "true"
            and int(info.get("exp", 0)) > int(time.time())
        )
    except (TypeError, ValueError) as exc:
        raise _OAuthFailure("oauth_failed") from exc
    email = (info.get("email") or "").strip().lower()
    if not valid or not email or not info.get("sub"):
        raise _OAuthFailure("oauth_failed")
    return info


def _check_domain(email: str, info: dict) -> None:
    allowed = get_settings().google_domain_list
    if not allowed:
        return
    domain = (info.get("hd") or email.split("@")[-1]).lower()
    if domain not in allowed:
        raise _OAuthFailure("domain")


def _provision_user(db: Session, info: dict, email: str) -> User:
    """Find-or-create the local user for a verified Google identity."""
    sub = str(info["sub"])
    user = db.query(User).filter(User.oauth_subject == sub).first()
    if user is None:
        user = db.query(User).filter(User.email == email).first()
    if user is not None:
        # Existing account (password or Google): stamp the subject so the link
        # is stable from here on. Role and name stay admin-managed.
        if not user.oauth_subject:
            user.oauth_subject = sub
        db.commit()
        db.refresh(user)
        return user
    name = (info.get("name") or email.split("@")[0]).strip()[:120] or email
    user = User(
        email=email,
        name=name,
        hashed_password=None,
        role="admin" if db.query(User).count() == 0 else "member",
        auth_provider="google",
        oauth_subject=sub,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/google/callback")
def google_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    s = get_settings()
    if not s.google_enabled:
        return _fail_redirect("disabled", "/")
    if error:
        # The user declined (or Google refused) at the consent screen.
        return _fail_redirect("denied", _safe_next(request.query_params.get("next")))
    try:
        next_path = _read_state(state, request.cookies.get(_STATE_COOKIE))
        if not code:
            raise _OAuthFailure("oauth_failed")
        identity = _validate_id_token(_exchange_code(code)["id_token"])
        email = str(identity["email"]).strip().lower()
        _check_domain(email, identity)
        user = _provision_user(db, identity, email)
    except _OAuthFailure as failure:
        return _fail_redirect(failure.code, _safe_next(request.query_params.get("next")))
    token = _make_token(user.email, user.role)
    resp = RedirectResponse(
        f"{_web_base()}/auth/callback"
        f"#access_token={quote(token, safe='')}"
        f"&role={quote(user.role, safe='')}"
        f"&next={quote(next_path, safe='')}",
        status_code=302,
    )
    resp.delete_cookie(_STATE_COOKIE)
    return resp


@router.get("/users", response_model=list[UserOut])
def list_users(_admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.created_at).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=body.email,
        name=body.name,
        hashed_password=_hash(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{uid}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_user(
    uid: int,
    current: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    if uid == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
