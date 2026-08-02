"""Simple in-memory per-IP rate limiting for expensive endpoints.

Single-process, best-effort — enough to stop accidental/careless abuse of the
multi-source scan (dozens of external API calls, ~1 minute) once the app is on
a public URL. Not a defense against a determined attacker.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

_hits: dict[str, list[float]] = defaultdict(list)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def too_many(request: Request, key: str, limit: int, window_seconds: int) -> bool:
    """True if this client already hit `key` >= limit times in the window
    (and records this attempt as a hit either way, so failed tries still count)."""
    bucket_key = f"{key}:{client_ip(request)}"
    now = time.time()
    hits = _hits[bucket_key]
    hits[:] = [t for t in hits if now - t < window_seconds]
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False
