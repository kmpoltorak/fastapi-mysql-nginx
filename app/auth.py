import os

from fastapi.security.api_key import APIKeyHeader
from fastapi import Security, HTTPException
from starlette.status import HTTP_403_FORBIDDEN

API_KEY = os.getenv("API_KEY")

################# AUTHENTICATION #################

api_key_header = APIKeyHeader(name="AccessToken", auto_error=False)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    """ Verification of authentication api token if its valid """
    if api_key_header == API_KEY:
        return api_key_header
    else:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Bad credentials")
