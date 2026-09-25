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

from utils import query

ACCESS_MINUTES = 15  # short: access tokens are not checked against the DB
REFRESH_HOURS = 8    # one working day, then log in again (with TOTP)
API_KEY_PREFIX = "mk_"
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

# ------------------- RANDOM TOKENS (refresh tokens, API keys) -------------------


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Fast unsalted hash is enough for 256-bit random tokens (unlike passwords)."""
    return hashlib.sha256(token.encode()).hexdigest()

# ------------------- TOTP -------------------


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

# ------------------- BEARER: JWT ACCESS TOKEN OR API KEY -------------------


def create_access_token(username: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MINUTES)
    return jwt.encode({"sub": username, "exp": expires}, os.environ["JWT_SECRET"], "HS256")


bearer = HTTPBearer(auto_error=False)
UNAUTHORIZED = HTTPException(status_code=401, detail="Not authenticated",
                             headers={"WWW-Authenticate": "Bearer"})


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> str:
    """Username from a JWT access token (people) or an API key (scripts), else 401."""
    if credentials is None:
        raise UNAUTHORIZED
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        rows = query("SELECT u.username FROM api_auth.api_keys k "
                     "JOIN api_auth.users u ON u.id = k.user_id WHERE k.key_hash=%s",
                     params=(token_hash(token),), auth=True)
        if not rows:
            raise UNAUTHORIZED
        return rows[0]
    # ponytail: JWT is stateless, a deleted user keeps access until it expires (ACCESS_MINUTES)
    try:
        return jwt.decode(token, os.environ["JWT_SECRET"], ["HS256"])["sub"]
    except jwt.InvalidTokenError:
        raise UNAUTHORIZED


def get_session_user(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> str:
    """Like get_current_user, but API keys are refused.

    Managing users, API keys and TOTP needs a real login, so a leaked key can't
    create more keys, change passwords or lock the owner out with TOTP.
    """
    if credentials and credentials.credentials.startswith(API_KEY_PREFIX):
        raise HTTPException(status_code=403,
                            detail="API keys can't manage users, keys or TOTP, log in instead")
    return get_current_user(credentials)
