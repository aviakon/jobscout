"""Ashby public job board API (no key needed).

https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
"""
from __future__ import annotations

import logging

import httpx

from app.sources.base import Connector, JobPosting
from app.sources.greenhouse import strip_html

log = logging.getLogger(__name__)


class AshbyConnector(Connector):
    name = "ashby"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, query: str = "", location: str = "") -> list[JobPosting]:
        out: list[JobPosting] = []
        with httpx.Client(timeout=20) as client:
            for b in self.boards:
                board, company = b["board"], b.get("company", b["board"])
                try:
                    r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
                    r.raise_for_status()
                    for j in r.json().get("jobs", []):
                        out.append(
                            JobPosting(
                                title=j.get("title", ""),
                                company=company,
                                source=self.name,
                                location=j.get("location", ""),
                                description=strip_html(j.get("descriptionHtml", ""))[:8000],
                                url=j.get("jobUrl", ""),
                                remote="remote" if j.get("isRemote") else "",
                                posted_at=(j.get("publishedAt") or "")[:10],
                            )
                        )
                except Exception as e:
                    log.warning("ashby fetch failed for %s: %s", board, e)
        return out
