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


_POSITION_NOISE = re.compile(
    r"^(?:was sent to|is sent to|applying to|applied to|your application to|"
    r"application to|applying for the|applying for|applying\s+\w+\s*$|"
    r"to\s+(?:the\s+)?(?=\w)|our\s+|received by|track it here|"
    r"\(?junior\s+data\s+engineer\s+position\)?$)",
    re.IGNORECASE,
)
_POSITION_TRAILING = re.compile(
    r"\s*(?:application|is complete|position[!.]?|!|\.|,\s*koen!?)$",
    re.IGNORECASE,
)
_POSITION_GENERIC = {
    "your application", "your application!", "applying to work",
    "applying", "track it here", "none",
}
_POSITION_ID_PREFIX = re.compile(r"^\d+\w+\s+")


def _clean_position(pos: str | None) -> str | None:
    """Strip noise patterns the AI commonly returns instead of null."""
    if not pos or not isinstance(pos, str):
        return None
    pos = pos.strip().strip('"')
    if pos.lower() in _POSITION_GENERIC:
        return None
    if _POSITION_NOISE.match(pos):
        # try to salvage by stripping the bad prefix
        cleaned = _POSITION_NOISE.sub("", pos).strip()
        pos = cleaned if len(cleaned) > 3 else None
    if pos:
        pos = _POSITION_TRAILING.sub("", pos).strip()
        pos = _POSITION_ID_PREFIX.sub("", pos).strip()
    if not pos or len(pos) < 4:
        return None
    return pos


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
                "You help a job seeker track their job applications.\n\n"
                "Given an email, return a JSON object with:\n"
                '  "status": one of applied / interview / offer / rejected / not_applicable\n'
                '  "position": the exact job title (e.g. "Software Engineer"), or null\n\n'
                "STATUS rules:\n"
                "  applied        — application submitted or received\n"
                "  interview      — interview invited, scheduled, reminder, or calendar invite\n"
                "  offer          — job offer extended\n"
                "  rejected       — application declined\n"
                "  not_applicable — promotions, newsletters, bank offers, research studies, unrelated\n\n"
                "POSITION rules — return the job title ONLY. Return null when:\n"
                "  - The subject only names a company with no role (e.g. 'sent to Synechron', 'applying to MongoDB')\n"
                "  - No specific role title is mentioned\n"
                "  - The email is not a job application\n"
                "Strip prefixes like 'our', 'the', job ID numbers. Strip suffixes like 'Application', 'is complete'.\n\n"
                "Examples (any industry):\n"
                '  "Your application was sent to Acme Corp" → {"status":"applied","position":null}\n'
                '  "Thank you for applying to Acme Corp" → {"status":"applied","position":null}\n'
                '  "We received your application for Marketing Manager at Acme" → {"status":"applied","position":"Marketing Manager"}\n'
                '  "Your application to Data Analyst at Acme Corp" → {"status":"applied","position":"Data Analyst"}\n'
                '  "Thank you for applying! - Junior Sales Representative, West Region" → {"status":"applied","position":"Junior Sales Representative"}\n'
                '  "Next Steps for Product Manager Application" → {"status":"applied","position":"Product Manager"}\n'
                '  "Update on your application for UX Designer, Entry Level" → {"status":"applied","position":"UX Designer, Entry Level"}\n'
                '  "We regret to inform you - Finance Analyst role" → {"status":"rejected","position":"Finance Analyst"}\n'
                '  "Interview Reminder with Acme Corp" → {"status":"interview","position":null}\n'
                '  "Upcoming Interview Starting Soon" → {"status":"interview","position":null}\n'
                '  "Invitation: Interview for Operations Manager role" → {"status":"interview","position":"Operations Manager"}\n'
                '  "Congratulations! We would like to offer you the Project Manager position" → {"status":"offer","position":"Project Manager"}\n'
                '  "Special offer: 50% off your next purchase" → {"status":"not_applicable","position":null}\n'
                '  "Limited Time Offer: Special Rates" → {"status":"not_applicable","position":null}\n'
                "Respond with only the JSON object."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Subject: {subject or ''}\n"
                    f"Body: {(body or '')[:800]}"
                ),
            }],
        )
        data = json.loads(response.content[0].text.strip())
        status = data.get("status", "applied")
        if status not in {"applied", "interview", "offer", "rejected", "not_applicable"}:
            status = "applied"
        position = _clean_position(data.get("position"))
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
