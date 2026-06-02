# FastAPI dependency that validates the Bearer JWT on every protected route and injects
# the decoded user payload. Import CurrentUser and use it as a type annotation in route handlers.

from fastapi import Header, HTTPException, Depends
from typing import Annotated
import jwt
import os

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")


def get_current_user(authorization: str = Header(...)) -> dict:
    try:
        token = authorization.removeprefix("Bearer ")
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


CurrentUser = Annotated[dict, Depends(get_current_user)]
