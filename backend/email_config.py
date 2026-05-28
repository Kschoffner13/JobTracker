# Databricks notebook source
# Shared email scanning configuration used by both the FastAPI backend (email_monitor.py)
# and the Databricks pipeline notebooks (email_sync.py, bronze_to_silver.py).
# Change JOB_QUERY or classification logic here and both pipelines pick it up automatically.

# COMMAND ----------

import base64
import hashlib
import re

# COMMAND ----------

JOB_QUERY = (
    'subject:("your application" OR "thank you for applying" OR "application received" '
    'OR interview OR "job offer" OR offer OR rejected OR "we regret" OR '
    '"not moving forward" OR "next steps" OR "hiring process" OR '
    '"got your resume" OR "application is complete")'
)

STATUS_PATTERNS = [
    (r"offer|pleased to offer|congratulations.*position|accept.*offer", "offer"),
    (r"interview|schedule.*call|speak with you|next steps|hiring manager", "interview"),
    (r"unfortunately|regret|not.*moving forward|decided.*not|no longer|other candidate", "rejected"),
    (r"received your application|thank you for apply|application.*received|we have received", "applied"),
]

# COMMAND ----------

def make_job_id(provider: str, thread_id: str) -> str:
    return hashlib.sha256(f"{provider}:{thread_id}".encode()).hexdigest()[:16]


def decode_body(payload: dict) -> str:
    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")[:2000]

    def _search(parts: list, mime: str) -> str:
        for part in parts:
            if part.get("mimeType") == mime:
                data = part.get("body", {}).get("data", "")
                if data:
                    return _decode(data)
            if "parts" in part:
                result = _search(part["parts"], mime)
                if result:
                    return result
        return ""

    if "parts" in payload:
        return _search(payload["parts"], "text/plain") or _search(payload["parts"], "text/html")

    data = payload.get("body", {}).get("data", "")
    return _decode(data) if data else ""


def detect_status(subject: str, body: str) -> str:
    text = f"{subject or ''} {body or ''}".lower()
    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return status
    return "applied"


def extract_company(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender or "")
    if not match:
        return "Unknown"
    domain = match.group(1)
    personal_domains = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "me", "googlemail"}
    parts = domain.split(".")
    company_part = parts[-2] if len(parts) >= 2 else parts[0]
    if company_part in personal_domains:
        return "Unknown"
    return company_part.capitalize()
