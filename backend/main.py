from dotenv import load_dotenv
load_dotenv()

import os
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.emails import router as emails_router
from api.applications import router as applications_router

app = FastAPI(title="Job Tracker API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://job-tracker-pzxqxt516-kschoffner-9548s-projects.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(emails_router)
app.include_router(applications_router)


@app.get("/")
def read_root():
    return {"message": "Job Tracker API"}
