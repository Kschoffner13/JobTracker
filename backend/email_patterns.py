# Known email patterns for supported job platforms.
# Add new platforms here — email_config.py imports everything and picks it up automatically.
# No logic lives here, only data: queries, regexes, domain maps, and pattern lists.

import re

# ─── Gmail search query ───────────────────────────────────────────────────────
# Subjects that indicate a job-related email. Add new phrases as needed.

JOB_QUERY = (
    'subject:("your application" OR "thank you for applying" OR "application received" '
    'OR interview OR "job offer" OR offer OR rejected OR "we regret" OR '
    '"not moving forward" OR "next steps" OR "hiring process" OR '
    '"got your resume" OR "application is complete" OR "Indeed Application")'
)

# ─── Application status classification ───────────────────────────────────────
# Checked in priority order: first match wins.

STATUS_PATTERNS = [
    # Offer — requires explicit language about extending/receiving a job offer to the candidate
    # Intentionally excludes "job offer" and "offer letter" alone — too common in marketing text
    (
        r"pleased to offer you|offer of employment|we.*like to extend.*offer|"
        r"extend an offer|we are offering you|formal offer|conditional offer|"
        r"we.*would like to offer you",
        "offer",
    ),
    # Interview — requires invitation or scheduling language
    (
        r"invite.*interview|schedule.*interview|interview.*invitation|"
        r"would like to interview|phone screen|moving.*forward.*interview|"
        r"invite you to.*interview",
        "interview",
    ),
    # Rejected — explicit declination language
    (
        r"unfortunately|regret to inform|not.*moving forward|decided.*not to move|"
        r"no longer.*consider|other candidate|position has been filled|"
        r"will not be moving",
        "rejected",
    ),
    # Applied — confirmation of receipt
    (
        r"received your application|thank you for apply|application.*received|"
        r"we have received|application.*submitted|application.*complete",
        "applied",
    ),
]

# ─── Platform source mapping ──────────────────────────────────────────────────
# Maps a substring of the sender's email domain → human-readable platform name.
# Add new platforms by appending an entry — no logic changes needed.

DOMAIN_SOURCE_MAP = {
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
    "indeed.com":             "Indeed",
}

# ─── ATS domains ──────────────────────────────────────────────────────────────
# Sender domains that belong to the ATS platform, NOT the actual employer.
# Company name must be extracted from the subject or body instead.

ATS_DOMAINS = {
    "greenhouse-mail.io", "hire.lever.co", "lever.co", "ashbyhq.com",
    "bamboohr.com", "myworkday.com", "dayforce.com",
    "talent.icims.com", "icims.com", "breezy-mail.com",
    "teamtailor-mail.com", "gem.com", "hire.humi.ca",
    "adp.com", "successfactors.com", "smartrecruiters.com",
    "applytojob.com", "ziprecruiter.com", "newtonsoftware.com",
    "lattice.com", "workable.com", "jobvite.com", "recruitee.com",
    "ultipro.com", "ultipro.innovationcu.ca",
    "indeed.com",
}

# Personal email domains — not associated with a company.
PERSONAL_DOMAINS = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "me", "googlemail"}

# Trailing words in ATS sender display names that identify the ATS, not the company.
HIRING_NOISE_RE = re.compile(
    r"\s+(?:hiring\s+team|careers?|hr|hires?|recruiting|talent(?:\s+acquisition)?|jobs?|notifications?)\s*$",
    re.IGNORECASE,
)

# ─── Indeed Apply ────────────────────────────────────────────────────────────
# Job posting URLs sit in href attributes in the raw HTML, e.g.:
# href="https://ca.indeed.com/viewjob?jk=abc123"
INDEED_JOB_URL_FROM_HTML_RE = re.compile(
    r'href=["\']?(https://[a-z.]*indeed\.com/(?:viewjob|rc/clk)[^"\'>\s]*)',
    re.IGNORECASE,
)

# Subject: "Indeed Application: Intermediate Front-End Developer"
INDEED_SUBJECT_POSITION_RE = re.compile(
    r"Indeed Application:\s*(.+)",
    re.IGNORECASE,
)

# Body: "The following items were sent to Canadian Cattle Identification Agency (CCIA). Good luck!"
INDEED_BODY_COMPANY_RE = re.compile(
    r"sent to (.+?)(?:\s*\([^)]+\))?\.",
    re.IGNORECASE,
)

# ─── Job URL extraction ───────────────────────────────────────────────────────

# LinkedIn "sent" email body: "View job: https://www.linkedin.com/comm/jobs/view/12345/..."
LINKEDIN_JOB_URL_RE = re.compile(
    r"View job:\s*(https://www\.linkedin\.com\S+?)(?:>|\s|$)",
    re.IGNORECASE,
)

# ZipRecruiter body: first link before the "Hi" greeting is the job link
ZIPRECRUITER_JOB_URL_RE = re.compile(
    r"(https://www\.ziprecruiter\.com/\S+?)(?:>|\s|$)",
    re.IGNORECASE,
)

# ─── LinkedIn ─────────────────────────────────────────────────────────────────

# Subject patterns: extract actual company name from LinkedIn notification subjects.
LINKEDIN_SUBJECT_PATTERNS = [
    r"application was sent to (.+?)(?:\.|,|$)",
    r"application to .+? at (.+?)(?:\.|,|$)",
    r"view (.+?) jobs and your next steps",
    r"application was viewed by (.+?)(?:\.|,|$)",
    r"complete your application to (.+?)(?:[–—,.]|$)",
]

# "Sent" email body structure:
#   Your application was sent to Hays
#
#   Python Developer      ← position (first non-blank line after confirmation)
#   Hays
#   Canada
LINKEDIN_SENT_BODY_RE = re.compile(
    r"Your application was sent to [^\n]+\n+([A-Z][^\n]{2,60})\n",
    re.IGNORECASE,
)

# ─── ZipRecruiter ─────────────────────────────────────────────────────────────

# Body: "Your application is complete for Platform Software Developer (2026-015) at Circle Cardiovascular Imaging!"
ZIPRECRUITER_BODY_COMPANY_RE = re.compile(
    r"Your application is complete for .+? at (.+?)!",
    re.IGNORECASE,
)
ZIPRECRUITER_BODY_POSITION_RE = re.compile(
    r"Your application is complete for (.+?)(?:\s+\([^)]+\))?\s+at ",
    re.IGNORECASE,
)

# Subject: 'Your "Full Stack Developer" application is complete'
ZIPRECRUITER_SUBJECT_POSITION_RE = re.compile(
    r'Your\s+"([^"]+)"\s+application',
    re.IGNORECASE,
)

# ─── Generic subject → company patterns ───────────────────────────────────────
# Used for ATS emails where neither display name nor platform-specific patterns match.

SUBJECT_COMPANY_PATTERNS = [
    r"\bat\s+(.+?)\s*[!.,]?\s*$",                                          # "Role at Company"
    r"\bapplying\s+(?:to|at|with)\s+(.+?)\s*[!.,]?\s*$",                  # "applying to Company"
    r"\bapplication\s+(?:to|at|with)\s+(.+?)\s*[!.,]?\s*$",               # "application to Company"
    r"\bwith\s+(.+?)\s*[!.,]?\s*$",                                        # "applying with Company"
    r"^(.+?)\s+[|]\s+(?:thank you|your application|application|we)",       # "Company | Thank you"
    r"^(.+?)\s+[-–—]\s+thank you",                                         # "Company - Thank you"
]

# ─── Platform validation ──────────────────────────────────────────────────────
# For known platforms, at least one pattern must match in subject+body for the
# email to be treated as a real application (not a promotional/ad email).
#
#   list of patterns → email is valid if any pattern matches
#   None             → always blocked (this domain never sends job application emails)
#
# Add new entries here to filter out ads from any platform without touching logic.

PLATFORM_VALIDATION: dict[str, list[str] | None] = {
    # LinkedIn: valid if the email explicitly references an application or applying action
    "linkedin.com": [
        r"application was sent",
        r"application was viewed",
        r"your application to",
        r"applied on",
        r"application confirmation",
        r"complete your application",
    ],
    # ZipRecruiter: valid only when confirming an application, not job recommendations
    "ziprecruiter.com": [
        r"application is complete",
        r'"[^"]+" application',
    ],
    # Research study platform — never a job application
    "userinterviews.com": None,
    # Indeed Apply confirmation emails (sender: indeedapply@indeed.com)
    "indeed.com": [r"indeed application", r"sent to"],
}

# ─── Position validation ──────────────────────────────────────────────────────
# Leading words/prepositions that generic regexes sometimes capture before the
# actual title — strip these before validating.
POSITION_STRIP_LEADING_RE = re.compile(
    r"^(?:to|at|for\s+the|for|with|our|the|a|an)\s+",
    re.IGNORECASE,
)

# Phrases that indicate the regex captured a sentence fragment, not a job title.
# Only applied to generic extractions — platform-specific ones are trusted.
POSITION_FRAGMENT_RE = re.compile(
    r"""
    \bwas\s+sent\b         |   # "was sent to"
    \bwere\s+sent\b        |   # "were sent to"
    \bapplying\s+to\b      |   # "applying to Company"
    \bapplied\s+to\b       |
    \byour\s+application\b |   # "your application to"
    \bapplication\s+to\b   |
    \btrack\s+it\s+here\b  |
    \binterest\s+in\b      |
    \binterest\s+working\b |
    ^\s*[—–→-]             |   # starts with a dash/arrow
    \bviewed\s+by\b        |   # "viewed by Company"
    \bsent\s+to\b              # "sent to Company"
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ─── Generic subject → position patterns ─────────────────────────────────────
# Fallback patterns when no platform-specific match is found.

POSITION_PATTERNS = [
    r"for (?:the |a |an )?(.+?)(?:\s+(?:role|position|job|opening)\b|\s+(?:at|with|@)\s+|\s*[-–—]\s*|\s*$)",
    r"applying (?:for|to) (?:the |a |an )?(.+?)(?:\s+(?:role|position|job)\b|\s+(?:at|with|@)\s+|\s*[-–—]|\s*$)",
    r"re:\s*(.+?)\s+(?:application|role|position|job)\b",
    r"^(.+?)\s*[-–—]\s*(?:application|your application|job application)\b",
    r"your\s+(.+?)\s+(?:application|candidacy)\b",
    r"application[:\s]+(?:for\s+)?(?:the\s+)?(.+?)(?:\s+(?:at|with)\s+|\s*[-–—]|\s*$)",
]
