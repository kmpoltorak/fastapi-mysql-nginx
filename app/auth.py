import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_MINUTES = 30
SCRYPT = {"n": 2**14, "r": 8, "p": 1}

# ------------------- PASSWORDS -------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest)


# Checked when the user doesn't exist, so response time doesn't reveal valid usernames
DUMMY_HASH = hash_password("")

# ------------------- TOTP -------------------


def verify_totp(secret: str, code: str) -> bool:
    # valid_window=1 accepts the previous/next 30 s code (clock drift)
    return bool(code) and pyotp.TOTP(secret).verify(code, valid_window=1)

# ------------------- JWT BEARER TOKENS -------------------


def create_token(username: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)
    return jwt.encode({"sub": username, "exp": expires}, os.environ["JWT_SECRET"], "HS256")


bearer = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> str:
    """Return username from a valid Bearer token or reject the request with 401."""
    # ponytail: stateless token, a deleted user keeps access until it expires (TOKEN_MINUTES)
    unauthorized = HTTPException(status_code=401, detail="Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        return jwt.decode(credentials.credentials, os.environ["JWT_SECRET"], ["HS256"])["sub"]
    except jwt.InvalidTokenError:
        raise unauthorized
