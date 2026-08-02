"""Lever public postings API (no key needed).

https://api.lever.co/v0/postings/{company}?mode=json
"""
from __future__ import annotations

import logging

import httpx

from app.sources.base import Connector, JobPosting
from app.sources.greenhouse import strip_html

log = logging.getLogger(__name__)


class LeverConnector(Connector):
    name = "lever"

    def __init__(self, boards: list[dict]):
        # boards: [{"board": "moonactive", "company": "Moon Active"}, ...]
        self.boards = boards

    def fetch(self, query: str = "", location: str = "") -> list[JobPosting]:
        out: list[JobPosting] = []
        with httpx.Client(timeout=20) as client:
            for b in self.boards:
                board, company = b["board"], b.get("company", b["board"])
                try:
                    r = client.get(f"https://api.lever.co/v0/postings/{board}", params={"mode": "json"})
                    r.raise_for_status()
                    for j in r.json():
                        cats = j.get("categories") or {}
                        workplace = (j.get("workplaceType") or "").lower()
                        out.append(
                            JobPosting(
                                title=j.get("text", ""),
                                company=company,
                                source=self.name,
                                location=cats.get("location", ""),
                                description=strip_html(j.get("descriptionPlain") or j.get("description", ""))[:8000],
                                url=j.get("hostedUrl", ""),
                                remote="remote" if workplace == "remote" else ("hybrid" if workplace == "hybrid" else ""),
                            )
                        )
                except Exception as e:
                    log.warning("lever fetch failed for %s: %s", board, e)
        return out
