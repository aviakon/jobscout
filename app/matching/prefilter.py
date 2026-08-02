"""Cheap keyword-overlap prefilter to shortlist jobs before LLM scoring."""
from __future__ import annotations

import re

from app.sources.base import JobPosting

_WORD_RE = re.compile(r"[a-z0-9֐-׿]+", re.UNICODE)
_STOP = {
    "and", "or", "the", "a", "an", "of", "to", "in", "for", "with", "on",
    "experience", "years", "team", "work", "role", "position", "job",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


def profile_terms(profile: dict) -> set[str]:
    """Weighted-ish bag of the candidate's important terms."""
    parts: list[str] = []
    parts += profile.get("skills", [])
    parts += profile.get("titles", [])
    parts += profile.get("industries", [])
    parts.append(profile.get("headline", ""))
    return _tokens(" ".join(parts))


def prefilter_score(profile_bag: set[str], job: JobPosting) -> float:
    """Fraction of the candidate's terms that appear in the job, title-weighted."""
    if not profile_bag:
        return 0.0
    title_tokens = _tokens(job.title)
    body_tokens = _tokens(f"{job.description} {job.location}")
    all_tokens = title_tokens | body_tokens

    overlap = profile_bag & all_tokens
    title_overlap = profile_bag & title_tokens
    base = len(overlap) / len(profile_bag)
    # bonus for matches appearing in the title
    bonus = 0.15 * (len(title_overlap) / max(1, len(profile_bag)))
    return round(min(1.0, base + bonus) * 100, 1)


def rank(profile: dict, jobs: list[JobPosting], top_n: int) -> list[tuple[JobPosting, float]]:
    bag = profile_terms(profile)
    scored = [(j, prefilter_score(bag, j)) for j in jobs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]
