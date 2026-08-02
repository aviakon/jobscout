"""JSearch API (RapidAPI) — aggregates Google for Jobs.

Covers LinkedIn, Indeed, AllJobs, Drushim etc. Requires a (free-tier) RapidAPI key.
"""
from __future__ import annotations

import logging

import httpx

from app import config
from app.sources.base import Connector, JobPosting

log = logging.getLogger(__name__)


class JSearchConnector(Connector):
    name = "jsearch"

    def __init__(self, api_key: str | None = None, pages: int = 2):
        self.api_key = api_key or config.RAPIDAPI_KEY
        self.pages = pages

    def fetch(self, query: str, location: str = "Israel") -> list[JobPosting]:
        if not self.api_key:
            log.info("jsearch skipped: no RAPIDAPI_KEY set")
            return []
        out: list[JobPosting] = []
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }
        with httpx.Client(timeout=30) as client:
            try:
                r = client.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params={
                        "query": f"{query} in {location}",
                        "num_pages": str(self.pages),
                        "date_posted": "month",
                    },
                )
                r.raise_for_status()
                for j in r.json().get("data", []):
                    city = j.get("job_city") or ""
                    country = j.get("job_country") or ""
                    out.append(
                        JobPosting(
                            title=j.get("job_title", ""),
                            company=j.get("employer_name", ""),
                            source=self.name,
                            location=", ".join(x for x in (city, country) if x),
                            description=(j.get("job_description") or "")[:8000],
                            url=j.get("job_apply_link") or j.get("job_google_link", ""),
                            remote="remote" if j.get("job_is_remote") else "",
                            posted_at=(j.get("job_posted_at_datetime_utc") or "")[:10],
                            extra={"publisher": j.get("job_publisher", "")},
                        )
                    )
            except Exception as e:
                log.warning("jsearch fetch failed for query %r: %s", query, e)
        return out
