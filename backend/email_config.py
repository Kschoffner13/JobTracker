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


def extract_position(subject: str, body: str) -> str | None:
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
    text = f"{subject or ''} {body or ''}".lower()
    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return status
    return "applied"


_PERSONAL_DOMAINS = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "me", "googlemail"}

# Maps sender email domain → human-readable application source
_DOMAIN_SOURCE_MAP = {
    "linkedin.com":           "LinkedIn",
    "greenhouse-mail.io":     "Greenhouse",
    "hire.lever.co":          "Lever",
    "lever.co":               "Lever",
    "ashbyhq.com":            "Ashby",
    "bamboohr.com":           "BambooHR",
    "myworkday.com":          "Workday",
    "dayforce.com":           "Dayforce",
    "talent.icims.com":       "iCIMS",
    "icims.com":              "iCIMS",
    "breezy-mail.com":        "Breezy",
    "teamtailor-mail.com":    "Teamtailor",
    "gem.com":                "Gem",
    "hire.humi.ca":           "Humi",
    "adp.com":                "ADP",
    "successfactors.com":     "SAP SuccessFactors",
    "smartrecruiters.com":    "SmartRecruiters",
    "applytojob.com":         "ApplyToJob",
    "ziprecruiter.com":       "ZipRecruiter",
    "newtonsoftware.com":     "Newton Software",
    "lattice.com":            "Lattice",
    "jobvite.com":            "Jobvite",
    "recruitee.com":          "Recruitee",
    "workable.com":           "Workable",
    "jobright.ai":            "Jobright",
    "micro1.ai":              "Micro1",
    "userinterviews.com":     "User Interviews",
    "ultipro.com":            "UKG Pro",
}

# Platforms where the sender domain is the ATS, not the actual employer
_ATS_DOMAINS = {
    "greenhouse-mail.io", "hire.lever.co", "lever.co", "ashbyhq.com",
    "bamboohr.com", "myworkday.com", "dayforce.com",
    "talent.icims.com", "icims.com", "breezy-mail.com",
    "teamtailor-mail.com", "gem.com", "hire.humi.ca",
    "adp.com", "successfactors.com", "smartrecruiters.com",
    "applytojob.com", "ziprecruiter.com", "newtonsoftware.com",
    "lattice.com", "workable.com", "jobvite.com", "recruitee.com",
    "ultipro.com", "ultipro.innovationcu.ca",
}

# Trailing words that are part of the ATS sender name, not the company
_HIRING_NOISE = re.compile(
    r"\s+(?:hiring\s+team|careers?|hr|hires?|recruiting|talent(?:\s+acquisition)?|jobs?|notifications?)\s*$",
    re.IGNORECASE,
)

def detect_source(sender: str) -> str:
    """Return the platform where the application was submitted based on the sender domain."""
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    if not domain_match:
        return "Unknown"
    domain = domain_match.group(1).lower()
    for ats_domain, source in _DOMAIN_SOURCE_MAP.items():
        if ats_domain in domain:
            return source
    parts = domain.split(".")
    base = parts[-2] if len(parts) >= 2 else parts[0]
    if base in _PERSONAL_DOMAINS:
        return "Unknown"
    return "Company Website"


# LinkedIn-specific subject patterns
_LINKEDIN_SUBJECT_PATTERNS = [
    r"application was sent to (.+?)(?:\.|,|$)",
    r"application to .+? at (.+?)(?:\.|,|$)",
    r"view (.+?) jobs and your next steps",
    r"application was viewed by (.+?)(?:\.|,|$)",
    r"complete your application to (.+?)(?:[–—,.]|$)",
]

# Generic subject patterns to extract company name from ATS emails
_SUBJECT_COMPANY_PATTERNS = [
    # "at Company" at end: "received your application for Role at Company"
    r"\bat\s+(.+?)\s*[!.,]?\s*$",
    # "applying to/at/with Company" at end
    r"\bapplying\s+(?:to|at|with)\s+(.+?)\s*[!.,]?\s*$",
    # "application to/at Company" at end
    r"\bapplication\s+(?:to|at|with)\s+(.+?)\s*[!.,]?\s*$",
    # "with Company" at end: "Thank you for applying with Company"
    r"\bwith\s+(.+?)\s*[!.,]?\s*$",
    # "Company | Thank you..." or "Company — ..." at start
    r"^(.+?)\s+[|]\s+(?:thank you|your application|application|we)",
    # "Company - Thank you..." at start
    r"^(.+?)\s+[-–—]\s+thank you",
]


def _parse_display_name(sender: str) -> str:
    """Extract the display name from 'Company Name <email@domain.com>' format."""
    m = re.match(r'^"?([^"<]+?)"?\s*<', sender or "")
    return m.group(1).strip() if m else ""


def _clean_display_name(name: str) -> str | None:
    """Strip ATS noise from display names and handle 'Person - Company' formats."""
    name = _HIRING_NOISE.sub("", name).strip()
    if not name:
        return None
    # "Person Name - Company" → take "Company" only when exactly 2 words precede the dash
    # (heuristic: 2-word names are likely people; 3+ words are likely company names)
    if " - " in name:
        before, _, after = name.partition(" - ")
        if len(before.split()) <= 2:
            name = after.strip()
    return name if len(name) > 1 else None


def _company_from_subject(subject: str) -> str | None:
    """Try to extract company name from common ATS subject line patterns."""
    for pattern in _SUBJECT_COMPANY_PATTERNS:
        m = re.search(pattern, subject, re.IGNORECASE)
        if m:
            company = m.group(1).strip().rstrip("!.,;–— ")
            if len(company) > 1:
                return company
    return None


def extract_company(sender: str, subject: str = "") -> str:
    domain_match = re.search(r"@([\w.-]+)", sender or "")
    domain = domain_match.group(1).lower() if domain_match else ""
    parts = domain.split(".")
    base = parts[-2] if len(parts) >= 2 else parts[0]

    # LinkedIn: parse the actual company from the subject line
    if "linkedin.com" in domain:
        if subject:
            for pattern in _LINKEDIN_SUBJECT_PATTERNS:
                m = re.search(pattern, subject, re.IGNORECASE)
                if m:
                    company = m.group(1).strip().rstrip(".,;")
                    if company:
                        return company
        return "LinkedIn"

    # Known ATS platforms: real company is NOT the sender domain
    if any(ats in domain for ats in _ATS_DOMAINS):
        # 1. Try subject line patterns first (most specific)
        if subject:
            company = _company_from_subject(subject)
            if company:
                return company
        # 2. Try sender display name
        display = _parse_display_name(sender)
        if display:
            company = _clean_display_name(display)
            if company:
                return company
        # 3. Try email address local part (e.g. autodesk@myworkday.com → Autodesk)
        if domain_match:
            local = sender.split("@")[0].split("<")[-1].strip()
            local = local.split("+")[0]
            local = re.sub(r"\.(hr|jobs?|careers?|hiring)$", "", local, flags=re.IGNORECASE)
            noise = {"noreply", "no-reply", "system", "notify", "notification",
                     "autoreply", "donotreply", "candidate", "reply", "autofill"}
            if local and local.lower() not in noise:
                return local.capitalize()
        return "Unknown"

    # Personal email domains
    if base in _PERSONAL_DOMAINS:
        return "Unknown"

    # Company-owned domain — use the domain name
    return base.capitalize()
