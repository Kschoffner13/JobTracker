from dotenv import load_dotenv
load_dotenv()

import os
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import auth
import email_monitor

app = FastAPI(title="Job Tracker API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(email_monitor.router)


@app.get("/")
def read_root():
    return {"message": "Job Tracker API"}
