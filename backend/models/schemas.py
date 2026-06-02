# Pydantic request/response models shared across the API.

from pydantic import BaseModel

VALID_STATUSES = {"applied", "interview", "offer", "rejected"}
VALID_JOB_TYPES = {"Remote", "Hybrid", "On-site"}


class ApplicationUpdate(BaseModel):
    company_name: str | None = None
    position: str | None = None
    current_status: str | None = None
    job_type: str | None = None
    job_url: str | None = None
