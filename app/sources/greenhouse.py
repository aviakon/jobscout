"""Greenhouse public job board API (no key needed).

https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
"""
from __future__ import annotations

import html
import logging
import re

import httpx

from app.sources.base import Connector, JobPosting

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", html.unescape(text or "")).strip()


class GreenhouseConnector(Connector):
    name = "greenhouse"

    def __init__(self, boards: list[dict]):
        # boards: [{"board": "wiz", "company": "Wiz"}, ...]
        self.boards = boards

    def fetch(self, query: str = "", location: str = "") -> list[JobPosting]:
        out: list[JobPosting] = []
        with httpx.Client(timeout=20) as client:
            for b in self.boards:
                board, company = b["board"], b.get("company", b["board"])
                try:
                    r = client.get(
                        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                        params={"content": "true"},
                    )
                    r.raise_for_status()
                    for j in r.json().get("jobs", []):
                        out.append(
                            JobPosting(
                                title=j.get("title", ""),
                                company=company,
                                source=self.name,
                                location=(j.get("location") or {}).get("name", ""),
                                description=strip_html(j.get("content", ""))[:8000],
                                url=j.get("absolute_url", ""),
                                posted_at=(j.get("updated_at") or "")[:10],
                            )
                        )
                except Exception as e:  # one bad board shouldn't kill the run
                    log.warning("greenhouse fetch failed for %s: %s", board, e)
        return out
