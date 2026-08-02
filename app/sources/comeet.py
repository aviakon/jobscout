"""Comeet careers-page API — Israeli ATS used by many Israeli startups.

Company career pages expose JSON at:
https://www.comeet.com/careers-api/2.0/company/{uid}/positions?token={token}&details=true
The uid+token pair is public (embedded in every Comeet careers page).
"""
from __future__ import annotations

import logging

import httpx

from app.sources.base import Connector, JobPosting
from app.sources.greenhouse import strip_html

log = logging.getLogger(__name__)


class ComeetConnector(Connector):
    name = "comeet"

    def __init__(self, boards: list[dict]):
        # boards: [{"uid": "...", "token": "...", "company": "..."}]
        self.boards = boards

    def fetch(self, query: str = "", location: str = "") -> list[JobPosting]:
        out: list[JobPosting] = []
        with httpx.Client(timeout=20) as client:
            for b in self.boards:
                company = b.get("company", "")
                try:
                    r = client.get(
                        f"https://www.comeet.com/careers-api/2.0/company/{b['uid']}/positions",
                        params={"token": b["token"], "details": "true"},
                    )
                    r.raise_for_status()
                    for j in r.json():
                        loc = j.get("location") or {}
                        details = j.get("details") or []
                        desc = " ".join(strip_html(d.get("value", "")) for d in details)
                        out.append(
                            JobPosting(
                                title=j.get("name", ""),
                                company=company,
                                source=self.name,
                                location=loc.get("name") or loc.get("city") or "",
                                description=desc[:8000],
                                url=j.get("url_comeet_hosted_page", ""),
                                posted_at=(j.get("time_updated") or "")[:10],
                            )
                        )
                except Exception as e:
                    log.warning("comeet fetch failed for %s: %s", company, e)
        return out
