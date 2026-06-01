# Databricks notebook source
# Shared email scanning logic used by both the FastAPI backend (email_monitor.py)
# and the Databricks pipeline notebooks (email_sync.py, bronze_to_silver.py).
# Platform-specific patterns live in email_patterns.py — add new platforms there.

# COMMAND ----------

import base64
import hashlib
import re
from email_patterns import (
    JOB_QUERY, STATUS_PATTERNS,
    DOMAIN_SOURCE_MAP, ATS_DOMAINS, PERSONAL_DOMAINS, HIRING_NOISE_RE,
    LINKEDIN_SUBJECT_PATTERNS, LINKEDIN_SENT_BODY_RE,
    LINKEDIN_JOB_URL_RE, ZIPRECRUITER_JOB_URL_RE,
    ZIPRECRUITER_BODY_COMPANY_RE, ZIPRECRUITER_BODY_POSITION_RE, ZIPRECRUITER_SUBJECT_POSITION_RE,
    SUBJECT_COMPANY_PATTERNS, POSITION_PATTERNS, PLATFORM_VALIDATION,
    POSITION_STRIP_LEADING_RE, POSITION_FRAGMENT_RE,
)

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

# COMMAND ----------

def _validate_position(pos: str) -> str | None:
    """Strip leading noise prefixes and reject fragment phrases.
    Returns the cleaned title or None if it doesn't look like a real job title.
    """
    pos = pos.strip().rstrip(".,;:!").strip('"\'')
    # Strip leading prepositions/articles the regex may have captured
    pos = POSITION_STRIP_LEADING_RE.sub("", pos).strip()
    if not pos or len(pos) < 4:
        return None
    # Reject if it looks like a sentence fragment, not a title
    if POSITION_FRAGMENT_RE.search(pos):
        return None
    word_count = len(pos.split())
    if word_count < 2 or word_count > 8 or len(pos) > 80:
        return None
    return pos


def extract_position(subject: str, body: str) -> str | None:
    # ── Trusted platform-specific extractors (no validation needed) ───────────

    # ZipRecruiter body: "Your application is complete for [Position] ([id]) at [Company]"
    if body:
        m = ZIPRECRUITER_BODY_POSITION_RE.search(body)
        if m:
            return m.group(1).strip()

    # ZipRecruiter subject: 'Your "[Position]" application is complete'
    m = ZIPRECRUITER_SUBJECT_POSITION_RE.search(subject or "")
    if m:
        return m.group(1).strip()

    # LinkedIn "sent" body: first non-blank line after the confirmation
    if body:
        m = LINKEDIN_SENT_BODY_RE.search(body)
        if m:
            pos = m.group(1).strip()
            if pos and not pos.startswith("http") and len(pos.split()) <= 8:
                return pos

    # ── Generic patterns — validate before returning ──────────────────────────
    for text in [(subject or ""), (body or "")[:500]]:
        for pattern in POSITION_PATTERNS:
            match = re.search(pattern, text.strip(), re.IGNORECASE)
            if match:
                pos = _validate_position(match.group(1))
                if pos:
                    return pos.title() if pos.islower() else pos
    return None


def is_application_email(sender: str, subject: str, body: str) -> bool:
    """Return False if this email is from a known platform but doesn't match
    the expected application email format — i.e. it's a promotional or ad email.
    Unknown senders always pass through.
    """
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    if not domain_match:
        return True
    domain = domain_match.group(1).lower()
    for platform_domain, patterns in PLATFORM_VALIDATION.items():
        if platform_domain in domain:
            if patterns is None:
                return False  # always blocked
            text = f"{subject or ''} {body or ''}".lower()
            return any(re.search(p, text, re.IGNORECASE) for p in patterns)
    return True  # unknown platform — let through


def extract_job_url(sender: str, body: str) -> str | None:
    """Extract a link to the job posting from known platform email formats."""
    if not body:
        return None
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    domain = domain_match.group(1).lower() if domain_match else ""

    if "linkedin.com" in domain:
        m = LINKEDIN_JOB_URL_RE.search(body)
        if m:
            url = m.group(1).rstrip(">.,")
            # Strip tracking params for a clean URL
            return url.split("?")[0].rstrip("/") + "/"

    if "ziprecruiter.com" in domain:
        m = ZIPRECRUITER_JOB_URL_RE.search(body)
        if m:
            return m.group(1).rstrip(">.,")

    return None


def detect_status(subject: str, body: str) -> str:
    text = f"{subject or ''} {body or ''}".lower()
    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return status
    return "applied"


def detect_source(sender: str) -> str:
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    if not domain_match:
        return "Unknown"
    domain = domain_match.group(1).lower()
    for ats_domain, source in DOMAIN_SOURCE_MAP.items():
        if ats_domain in domain:
            return source
    parts = domain.split(".")
    base = parts[-2] if len(parts) >= 2 else parts[0]
    if base in PERSONAL_DOMAINS:
        return "Unknown"
    return "Company Website"

# COMMAND ----------

def _parse_display_name(sender: str) -> str:
    m = re.match(r'^"?([^"<]+?)"?\s*<', sender or "")
    return m.group(1).strip() if m else ""


def _clean_display_name(name: str) -> str | None:
    name = HIRING_NOISE_RE.sub("", name).strip()
    if not name:
        return None
    if " - " in name:
        before, _, after = name.partition(" - ")
        if len(before.split()) <= 2:
            name = after.strip()
    return name if len(name) > 1 else None


def _company_from_subject(subject: str) -> str | None:
    for pattern in SUBJECT_COMPANY_PATTERNS:
        m = re.search(pattern, subject, re.IGNORECASE)
        if m:
            company = m.group(1).strip().rstrip("!.,;–— ")
            if len(company) > 1:
                return company
    return None


def extract_company(sender: str, subject: str = "", body: str = "") -> str:
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    domain = domain_match.group(1).lower() if domain_match else ""
    parts = domain.split(".")
    base = parts[-2] if len(parts) >= 2 else parts[0]

    # ZipRecruiter: company is in the body confirmation line
    if "ziprecruiter.com" in domain and body:
        m = ZIPRECRUITER_BODY_COMPANY_RE.search(body)
        if m:
            return m.group(1).strip()

    # LinkedIn: company is in the subject notification
    if "linkedin.com" in domain:
        if subject:
            for pattern in LINKEDIN_SUBJECT_PATTERNS:
                m = re.search(pattern, subject, re.IGNORECASE)
                if m:
                    company = m.group(1).strip().rstrip(".,;")
                    if company:
                        return company
        return "LinkedIn"

    # Known ATS: try subject → display name → email prefix
    if any(ats in domain for ats in ATS_DOMAINS):
        if subject:
            company = _company_from_subject(subject)
            if company:
                return company
        display = _parse_display_name(sender)
        if display:
            company = _clean_display_name(display)
            if company:
                return company
        if domain_match:
            local = sender.split("@")[0].split("<")[-1].strip()
            local = local.split("+")[0]
            local = re.sub(r"\.(hr|jobs?|careers?|hiring)$", "", local, flags=re.IGNORECASE)
            noise = {"noreply", "no-reply", "system", "notify", "notification",
                     "autoreply", "donotreply", "candidate", "reply", "autofill"}
            if local and local.lower() not in noise:
                return local.capitalize()
        return "Unknown"

    # Personal domain
    if base in PERSONAL_DOMAINS:
        return "Unknown"

    # Company-owned domain
    return base.capitalize()
