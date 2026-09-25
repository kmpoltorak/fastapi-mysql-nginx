import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import pyotp
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ACCESS_MINUTES = 15  # clients just request a new token when it expires
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
SCRYPT = {"n": 2**14, "r": 8, "p": 1}

# ------------------- PASSWORDS AND CLIENT SECRETS -------------------


def hash_password(password: str) -> str:
    """One-way scrypt hash with random salt; the password can't be recovered from it."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest)


# Checked when the user/client doesn't exist, so response time doesn't reveal valid names
DUMMY_HASH = hash_password("")


def new_secret() -> str:
    return secrets.token_urlsafe(32)

# ------------------- TOTP (application users) -------------------


def totp_step(secret: str, code: Optional[str], last_step: Optional[int] = None) -> Optional[int]:
    """Return the 30 s time step the code belongs to, or None if invalid.

    Accepts the previous/current/next step (clock drift). Steps <= last_step were
    already used, so the same code can't be replayed.
    """
    if not code:
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time()) // totp.interval
    for step in (now - 1, now, now + 1):
        if (last_step is None or step > last_step) and \
                hmac.compare_digest(totp.at(step * totp.interval), code):
            return step
    return None

# ------------------- JWT FOR API CLIENTS -------------------


def create_access_token(client_id: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MINUTES)
    return jwt.encode({"sub": client_id, "exp": expires}, os.environ["JWT_SECRET"], "HS256")


bearer = HTTPBearer(auto_error=False)


def get_current_client(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> str:
    """client_id from a valid Bearer JWT, else 401."""
    # ponytail: JWT is stateless, a deleted client keeps access until it expires (ACCESS_MINUTES)
    unauthorized = HTTPException(status_code=401, detail="Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        return jwt.decode(credentials.credentials, os.environ["JWT_SECRET"], ["HS256"])["sub"]
    except jwt.InvalidTokenError:
        raise unauthorized
