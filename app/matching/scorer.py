"""LLM match scoring: rate a job 0-100 against a candidate profile with reasons."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from app import config
from app.resume.parser import _loads_lenient
from app.sources.base import JobPosting

log = logging.getLogger(__name__)

SCORE_SYSTEM = """You are a job-matching expert. Given a candidate profile and a single
job posting, judge how well the candidate fits the job. Be honest and discriminating;
do not inflate scores. Consider skills, seniority, titles, industry, and location.
The content may be in Hebrew or English; write your reasons in the job's language.
Do not use em-dashes or en-dashes in your output; use periods or commas instead.

Return ONLY valid JSON:
{
  "score": integer 0-100,        // overall fit
  "verdict": string,             // one short sentence
  "why": [string],               // 2-4 concrete reasons the candidate matches
  "gaps": [string]               // 0-3 things missing or weak for this role
}"""


def _score_one(client, profile: dict, job: JobPosting) -> dict:
    prompt = (
        f"CANDIDATE PROFILE:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"JOB POSTING:\n"
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n"
        f"Remote: {job.remote or 'unspecified'}\n\n"
        f"Description:\n{job.description[:6000]}"
    )
    try:
        msg = client.messages.create(
            model=config.SCORING_MODEL,
            max_tokens=700,
            system=SCORE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        data = _loads_lenient(text)
        return {
            "score": float(max(0, min(100, data.get("score", 0)))),
            "verdict": str(data.get("verdict", "")),
            "why": [str(x) for x in data.get("why", [])][:4],
            "gaps": [str(x) for x in data.get("gaps", [])][:3],
        }
    except Exception as e:
        log.warning("scoring failed for %s @ %s: %s", job.title, job.company, e)
        return {"score": 0.0, "verdict": "", "why": [], "gaps": []}


def score_jobs(profile: dict, jobs: list[JobPosting]) -> list[dict]:
    """Score jobs. Uses Claude when a key is set, else the offline scorer."""
    if not config.ANTHROPIC_API_KEY:
        from app.matching import heuristic_scorer

        log.info("no API key — scoring jobs with offline heuristic engine")
        return heuristic_scorer.score_jobs(profile, jobs)

    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    with ThreadPoolExecutor(max_workers=config.SCORER_MAX_CONCURRENCY) as pool:
        return list(pool.map(lambda j: _score_one(client, profile, j), jobs))


def gap_analysis(profile: dict, scored: list[tuple[JobPosting, dict]], min_score: float = 50) -> list[dict]:
    """Which skills recur across good-fit jobs but are missing from the resume.

    Produces the actionable "skill X appears in N% of your matches but not your
    profile" insight, tallied per-skill (not per raw gap string).
    """
    from collections import Counter

    from app.matching.heuristic_scorer import _skills_in
    from app.resume.heuristic import _lc

    profile_skills = set(profile.get("skills", []))
    good = [j for j, s in scored if s["score"] >= min_score]
    total = max(1, len(good))

    counter: Counter[str] = Counter()
    for job in good:
        job_skills = _skills_in(_lc(f"{job.title} {job.description}"))
        for skill in job_skills - profile_skills:
            counter[skill] += 1

    return [
        {"skill": skill, "count": n, "pct": round(100 * n / total)}
        for skill, n in counter.most_common(8)
        if n >= 2  # only recurring gaps are worth surfacing
    ]
