"""Auth: login, current user, user management (admin-only CRUD)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import jwt
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
    if user is None or not _verify(body.password, user.hashed_password):
        _record_failure(key, s.login_lockout_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _clear_failures(key)
    return TokenOut(access_token=_make_token(user.email, user.role), role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


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
