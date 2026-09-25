import os
import logging

from fastapi.security.api_key import APIKeyHeader
from fastapi import Security, HTTPException
from starlette.status import HTTP_403_FORBIDDEN


# Support multiple API keys (comma-separated in env), and handle missing env variable gracefully
API_KEYS = os.getenv("API_KEY", "").split(",") if os.getenv("API_KEY") else []
if not API_KEYS or API_KEYS == [""]:
    logging.warning("No API_KEY set in environment. All requests will be rejected.")

# ------------------- API AUTHENTICATION -------------------

api_key_header = APIKeyHeader(name="AccessToken", auto_error=False)


async def get_api_key(api_key_header: str = Security(api_key_header)):
    """
    Verification of authentication API token.
    Supports multiple keys via comma-separated env variable.
    """
    if not API_KEYS or API_KEYS == [""]:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="API authentication not configured on server."
        )
    if api_key_header and api_key_header in [k.strip() for k in API_KEYS]:
        return api_key_header
    logging.warning(f"Failed API key attempt: {api_key_header}")
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN,
        detail="Bad credentials"
    )
