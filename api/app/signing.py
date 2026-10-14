"""Expiring signed download links (HMAC over job_id + expiry, keyed by JWT_SECRET).

ponytail: a stdlib hmac signature, not JWT — we only need "is this link valid and
unexpired". No dependency, no token format to parse.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.config import get_settings


def _sign(job_id: int, exp: int, purpose: str = "") -> str:
    secret = get_settings().jwt_secret.encode()
    # The purpose is inside the signed material, so a link minted to stream one
    # job's progress cannot be replayed as a link to download its CSV.
    payload = f"{purpose}:{job_id}:{exp}" if purpose else f"{job_id}:{exp}"
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_download_url(job_id: int) -> str:
    exp = int(time.time()) + get_settings().download_url_ttl_seconds
    return f"/jobs/{job_id}/download?exp={exp}&sig={_sign(job_id, exp)}"


def verify(job_id: int, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(job_id, exp))


# Long enough to outlive a job that runs all day, because EventSource reconnects
# on its own and a ticket that expires mid-run would silently stop the feed.
PROGRESS_TICKET_TTL_SECONDS = 12 * 3600


def make_progress_url(job_id: int) -> str:
    """A ticket for ONE job's progress stream.

    EventSource cannot set an Authorization header, so this used to take the
    caller's 24h session JWT as a query parameter — which then sat in uvicorn
    access logs, any proxy log, and browser history, granting everything that
    session could do. This grants exactly one thing: read progress for this job.
    """
    exp = int(time.time()) + PROGRESS_TICKET_TTL_SECONDS
    return f"/jobs/{job_id}/progress?exp={exp}&sig={_sign(job_id, exp, 'progress')}"


def verify_progress(job_id: int, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(job_id, exp, "progress"))
