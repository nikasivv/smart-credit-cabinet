"""Аутентификация и авторизация.

* пароли — PBKDF2-HMAC-SHA256, 310 000 итераций (рекомендация OWASP), стандартная библиотека;
* токен — JWT HS256 с ограниченным временем жизни;
* RBAC: роли CLIENT, ANALYST, RISK_ADMIN; клиент видит только заявки своей компании
  (проверка на уровне объекта — в сервисном слое).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

_ITER = 310_000
_bearer = HTTPBearer(auto_error=False)

ROLE_CLIENT, ROLE_ANALYST, ROLE_RISK = "CLIENT", "ANALYST", "RISK_ADMIN"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, hash_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "role": user.role, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_ttl_minutes), "iss": "scc"}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _unauthorized(msg: str = "Требуется вход в систему") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=msg, headers={"WWW-Authenticate": "Bearer"})


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"], issuer="scc")
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Сессия истекла, войдите снова")
    except jwt.InvalidTokenError:
        raise _unauthorized("Недействительный токен")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise _unauthorized()
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для этого действия")
        return user
    return dep


def mask_inn(inn: str | None) -> str:
    """Маскирование для логов: персональные и коммерческие данные не пишутся в логи целиком."""
    if not inn:
        return "-"
    return inn[:4] + "*" * (len(inn) - 6) + inn[-2:]
