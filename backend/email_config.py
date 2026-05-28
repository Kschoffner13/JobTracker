# Databricks notebook source
# Shared email scanning configuration used by both the FastAPI backend (email_monitor.py)
# and the Databricks pipeline notebooks (email_sync.py, bronze_to_silver.py).
# Change JOB_QUERY or classification logic here and both pipelines pick it up automatically.
# Set USE_AI_CLASSIFICATION=true in .env to use Claude Haiku instead of regex patterns.

# COMMAND ----------

import base64
import hashlib
import json
import os
import re

USE_AI_CLASSIFICATION = os.getenv("USE_AI_CLASSIFICATION", "false").lower() == "true"

# COMMAND ----------

JOB_QUERY = (
    'subject:("your application" OR "thank you for applying" OR "application received" '
    'OR interview OR "job offer" OR offer OR rejected OR "we regret" OR '
    '"not moving forward" OR "next steps" OR "hiring process" OR '
    '"got your resume" OR "application is complete")'
)

STATUS_PATTERNS = [
    (r"pleased to offer|offer of employment|extend.*offer|we.*like to offer|offer letter|job offer", "offer"),
    (r"invite.*interview|schedule.*interview|interview.*invitation|would like to interview|phone screen|moving.*forward.*interview", "interview"),
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


_POSITION_PATTERNS = [
    # "for [the/a] POSITION [role/position/job] [at/with/-]"
    r"for (?:the |a |an )?(.+?)(?:\s+(?:role|position|job|opening)\b|\s+(?:at|with|@)\s+|\s*[-–—]\s*|\s*$)",
    # "applying for/to [the] POSITION"
    r"applying (?:for|to) (?:the |a |an )?(.+?)(?:\s+(?:role|position|job)\b|\s+(?:at|with|@)\s+|\s*[-–—]|\s*$)",
    # "Re: POSITION Application/Role"
    r"re:\s*(.+?)\s+(?:application|role|position|job)\b",
    # "POSITION - Application" at start of subject
    r"^(.+?)\s*[-–—]\s*(?:application|your application|job application)\b",
    # "your POSITION application/candidacy"
    r"your\s+(.+?)\s+(?:application|candidacy)\b",
    # "application: [for] POSITION"
    r"application[:\s]+(?:for\s+)?(?:the\s+)?(.+?)(?:\s+(?:at|with)\s+|\s*[-–—]|\s*$)",
]


def _classify_with_ai(subject: str, body: str) -> dict | None:
    """Call Claude Haiku to classify status and extract position in one API call.
    Returns {"status": str, "position": str | None} or None on any failure.
    Disable by setting USE_AI_CLASSIFICATION=false in .env.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            system=(
                "You help a job seeker track their job applications by analyzing emails.\n\n"
                "Extract two things:\n\n"
                "1. STATUS — the current stage of the job application:\n"
                "   applied       — application was submitted or received by the employer\n"
                "   interview     — the person is invited to interview, or an interview is being scheduled/confirmed\n"
                "   offer         — a job offer has been extended to the person\n"
                "   rejected      — the application was declined or they are not moving forward\n"
                "   not_applicable — this is NOT a job application email (e.g. promotions, newsletters,\n"
                "                   marketing emails, research studies, bank offers, unrelated)\n\n"
                "2. POSITION — the specific job title or role the person applied for.\n"
                "   Extract ONLY the role title itself, e.g. 'Senior Software Engineer' or 'Full Stack Developer'.\n"
                "   Do NOT include: company names, action words ('applying to', 'sent to', 'applying for'),\n"
                "   filler phrases, or anything that is not the actual job title.\n"
                "   Return null if the email does not mention a specific role title.\n\n"
                "Respond with only a JSON object, no explanation."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Subject: {subject or ''}\n"
                    f"Body: {(body or '')[:800]}\n\n"
                    'Return: {"status": "applied|interview|offer|rejected|not_applicable", "position": "job title or null"}'
                ),
            }],
        )
        data = json.loads(response.content[0].text.strip())
        status = data.get("status", "applied")
        if status not in {"applied", "interview", "offer", "rejected", "not_applicable"}:
            status = "applied"
        position = data.get("position")
        if not isinstance(position, str) or not position.strip():
            position = None
        return {"status": status, "position": position}
    except Exception:
        return None


def extract_position(subject: str, body: str) -> str | None:
    if USE_AI_CLASSIFICATION:
        result = _classify_with_ai(subject, body)
        # not_applicable means no real job title to extract
        if result and result["status"] != "not_applicable":
            return result["position"]
        if result and result["status"] == "not_applicable":
            return None
    for text in [(subject or ""), (body or "")[:500]]:
        for pattern in _POSITION_PATTERNS:
            match = re.search(pattern, text.strip(), re.IGNORECASE)
            if match:
                pos = match.group(1).strip().rstrip(".,;:")
                word_count = len(pos.split())
                if 2 <= word_count <= 8 and len(pos) <= 80:
                    return pos.title() if pos.islower() else pos
    return None


def detect_status(subject: str, body: str) -> str:
    if USE_AI_CLASSIFICATION:
        result = _classify_with_ai(subject, body)
        if result and result["status"] != "not_applicable":
            return result["status"]
        # not_applicable: fall through to regex as a second opinion
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
