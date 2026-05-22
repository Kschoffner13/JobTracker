from fastapi import APIRouter, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel
from googleapiclient.discovery import build
import google_auth_oauthlib.flow
import jwt
import os
import datetime
from db import get_cursor, table
from email_monitor import run_scan

router = APIRouter(prefix="/api/auth", tags=["auth"])

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def make_jwt(user_id: str, email: str, name: str, picture: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=30),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def decode_jwt(authorization: str) -> dict:
    try:
        token = authorization.removeprefix("Bearer ")
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


class GoogleAuthRequest(BaseModel):
    code: str


@router.post("/google")
def google_auth(body: GoogleAuthRequest, background_tasks: BackgroundTasks):
    flow = google_auth_oauthlib.flow.Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = "postmessage"

    try:
        flow.fetch_token(code=body.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")

    creds = flow.credentials

    service = build("oauth2", "v2", credentials=creds)
    info = service.userinfo().get().execute()

    user_id = info["id"]
    email = info["email"]
    new_refresh_token = creds.refresh_token

    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT refresh_token FROM {table('system', 'users')} WHERE user_id = ?",
            [user_id],
        )
        existing = cursor.fetchone()

    if existing:
        refresh_token = new_refresh_token or existing[0]
        with get_cursor() as cursor:
            cursor.execute(
                f"UPDATE {table('system', 'users')} "
                f"SET email=?, name=?, picture=?, refresh_token=?, last_login=current_timestamp() "
                f"WHERE user_id=?",
                [email, info.get("name", ""), info.get("picture", ""), refresh_token, user_id],
            )
        is_new_user = False
    else:
        with get_cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table('system', 'users')} "
                f"(user_id, email, name, picture, refresh_token, created_at, last_login) "
                f"VALUES (?, ?, ?, ?, ?, current_timestamp(), current_timestamp())",
                [user_id, email, info.get("name", ""), info.get("picture", ""), new_refresh_token],
            )
        is_new_user = True

    if is_new_user:
        print(f"[auth] New user {email} — starting 6-month background scan")
        background_tasks.add_task(run_scan, user_id, new_refresh_token)

    print(f"[auth] User signed in: {email} ({'new' if is_new_user else 'returning'})")

    return {
        "token": make_jwt(user_id, email, info.get("name", ""), info.get("picture", "")),
        "user": {
            "id": user_id,
            "email": email,
            "name": info.get("name", ""),
            "picture": info.get("picture", ""),
        },
    }


@router.get("/me")
def get_me(authorization: str = Header(...)):
    payload = decode_jwt(authorization)

    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT user_id, email, name, picture FROM {table('system', 'users')} WHERE user_id = ?",
            [payload["sub"]],
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {"id": row[0], "email": row[1], "name": row[2], "picture": row[3]}


@router.post("/logout")
def logout(authorization: str = Header(...)):
    decode_jwt(authorization)
    return {"ok": True}
