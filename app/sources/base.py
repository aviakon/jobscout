"""Connector interface and the normalized job posting shape all sources produce."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class JobPosting:
    """A job posting normalized to a common shape, regardless of source."""

    title: str
    company: str
    source: str
    location: str = ""
    description: str = ""
    url: str = ""
    remote: str = ""      # remote / hybrid / onsite / ""
    posted_at: str = ""   # ISO date string when known
    # Where the posting actually came from, for display. For a company ATS board this
    # is the board name; for an aggregator it's the original publisher (e.g. "LinkedIn").
    source_detail: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        """Stable key so the same job from two sources collapses to one row."""
        norm = f"{_normalize(self.company)}|{_normalize(self.title)}"
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


_PUNCT_RE = re.compile(r"[^\w\s֐-׿]", re.UNICODE)  # keep Hebrew letters
_WS_RE = re.compile(r"\s+")
# Suffixes that vary between postings of the same job
_NOISE_WORDS = {"ltd", "inc", "llc", "בעמ", "בע״מ"}


def _normalize(text: str) -> str:
    text = _PUNCT_RE.sub(" ", text.lower())
    words = [w for w in _WS_RE.split(text) if w and w not in _NOISE_WORDS]
    return " ".join(words)


def dedupe(postings: list[JobPosting]) -> list[JobPosting]:
    """Collapse duplicate postings, preferring the one with the longer description."""
    best: dict[str, JobPosting] = {}
    for p in postings:
        key = p.dedupe_key
        existing = best.get(key)
        if existing is None or len(p.description) > len(existing.description):
            best[key] = p
    return list(best.values())


class Connector:
    """Base class: each job source implements fetch()."""

    name: str = "base"

    def fetch(self, query: str, location: str = "Israel") -> list[JobPosting]:
        raise NotImplementedError
