"""Password hashing, JWT, and magic-link tokens.

- Passwords: Argon2id via passlib.
- Session tokens: JWT (HS256) signed with JWT_SECRET; access tokens carry
  `sub` (user_id), `org` (current_org_id) and `exp`. Refresh tokens carry
  `sub`, `type=refresh`, `exp`.
- Magic links: short, single-use, signed via itsdangerous URLSafeTimedSerializer
  with a salt of "magic-link". Payload is the email being logged in as.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

from salespilot.config import get_settings

_pw_ctx = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pw_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pw_ctx.verify(plain, hashed)


# --------------------- JWT ---------------------

JWT_ALG = "HS256"

TokenKind = Literal["access", "refresh"]


def create_access_token(user_id: UUID, org_id: UUID | None) -> tuple[str, datetime]:
    settings = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=settings.jwt_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "type": "access",
        "exp": exp,
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALG)
    return token, exp


def create_refresh_token(user_id: UUID) -> tuple[str, datetime]:
    settings = get_settings()
    exp = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": exp,
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALG)
    return token, exp


class TokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenKind) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=[JWT_ALG]
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenError("expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("invalid") from e

    if payload.get("type") != expected_type:
        raise TokenError(f"wrong token type (expected {expected_type})")
    return payload


# --------------------- Magic links ---------------------

_MAGIC_SALT = "magic-link-v1"


def _magic_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(
        settings.app_secret_key.get_secret_value(), salt=_MAGIC_SALT
    )


def create_magic_link_token(email: str) -> str:
    """Returns a URL-safe, signed token containing the email."""
    return _magic_serializer().dumps({"email": email.lower()})


def verify_magic_link_token(token: str) -> str:
    """Returns the email if the token is valid and not expired.

    Raises TokenError otherwise.
    """
    settings = get_settings()
    max_age = settings.magic_link_ttl_minutes * 60
    try:
        data = _magic_serializer().loads(token, max_age=max_age)
    except SignatureExpired as e:
        raise TokenError("expired") from e
    except BadSignature as e:
        raise TokenError("invalid") from e
    return str(data["email"]).lower()
