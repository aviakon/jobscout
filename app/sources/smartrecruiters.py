"""SmartRecruiters public postings API (no key needed).

https://api.smartrecruiters.com/v1/companies/{company}/postings

Note: this endpoint returns HTTP 200 with totalFound=0 for *any* slug, including
nonsense ones, so a board only belongs in companies.yaml after confirming it
actually returns postings.
"""
from __future__ import annotations

import logging

import httpx

from app.sources.base import Connector, JobPosting

log = logging.getLogger(__name__)

PAGE_LIMIT = 100


class SmartRecruitersConnector(Connector):
    name = "smartrecruiters"

    def __init__(self, boards: list[dict]):
        # boards: [{"board": "fiverr", "company": "Fiverr"}, ...]
        self.boards = boards

    def fetch(self, query: str = "", location: str = "") -> list[JobPosting]:
        out: list[JobPosting] = []
        with httpx.Client(timeout=20) as client:
            for b in self.boards:
                board, company = b["board"], b.get("company", b["board"])
                try:
                    out += self._fetch_board(client, board, company)
                except Exception as e:  # one bad board shouldn't kill the run
                    log.warning("smartrecruiters fetch failed for %s: %s", board, e)
        return out

    def _fetch_board(self, client: httpx.Client, board: str, company: str) -> list[JobPosting]:
        out: list[JobPosting] = []
        offset = 0
        while True:
            r = client.get(
                f"https://api.smartrecruiters.com/v1/companies/{board}/postings",
                params={"limit": str(PAGE_LIMIT), "offset": str(offset)},
            )
            r.raise_for_status()
            data = r.json()
            postings = data.get("content") or []
            for j in postings:
                loc = j.get("location") or {}
                city = loc.get("city") or ""
                country = loc.get("country") or ""
                out.append(
                    JobPosting(
                        title=j.get("name", ""),
                        company=company,
                        source=self.name,
                        location=", ".join(x for x in (city, country) if x),
                        # the list endpoint has no body; the title/location still
                        # carry enough signal for matching, and the link has detail
                        description=j.get("name", ""),
                        url=(j.get("applyUrl")
                             or f"https://jobs.smartrecruiters.com/{board}/{j.get('id', '')}"),
                        remote="remote" if loc.get("remote") else "",
                        posted_at=(j.get("releasedDate") or "")[:10],
                    )
                )
            offset += PAGE_LIMIT
            if len(postings) < PAGE_LIMIT or offset >= (data.get("totalFound") or 0):
                break
        return out
