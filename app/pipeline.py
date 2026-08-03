"""End-to-end pipeline: fetch -> normalize -> dedupe -> prefilter -> score -> persist."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.matching import prefilter, scorer
from app.models import Candidate, Job, Match
from app.sources.base import JobPosting, dedupe
from app.sources.registry import build_connectors, default_queries

log = logging.getLogger(__name__)


def build_queries(profile: dict) -> list[str]:
    """Search terms for query-driven sources (JSearch), derived from the resume
    and the candidate's roles-of-interest preference."""
    from app import preferences as prefs_mod

    queries: list[str] = []
    for t in profile.get("titles", [])[:3]:
        if t:
            queries.append(t)
    if not queries and profile.get("headline"):
        queries.append(profile["headline"])
    queries = queries or default_queries()
    queries = prefs_mod.augment_queries(queries, profile.get("preferences", {}))
    # Hard budget: every query costs a billed request on the aggregator's free
    # tier, and bilingual expansion can easily triple the list.
    return queries[: max(1, config.JSEARCH_MAX_QUERIES)]


def fetch_all(profile: dict, location: str = "Israel") -> list[JobPosting]:
    """Run every connector and return the combined, de-duplicated postings."""
    queries = build_queries(profile)
    postings: list[JobPosting] = []
    for connector in build_connectors():
        try:
            if connector.name == "jsearch":
                for q in queries:
                    postings += connector.fetch(q, location=location)
            else:
                postings += connector.fetch()
        except Exception as e:  # never let one source sink the run
            log.warning("connector %s failed: %s", connector.name, e)
    log.info("fetched %d raw postings across sources", len(postings))
    return dedupe(postings)


def _upsert_job(session: Session, p: JobPosting) -> Job:
    job = session.scalar(select(Job).where(Job.dedupe_key == p.dedupe_key))
    if job is None:
        job = Job(dedupe_key=p.dedupe_key)
        session.add(job)
    job.title = p.title
    job.company = p.company
    job.location = p.location
    job.description = p.description
    job.url = p.url
    job.source = p.source
    job.source_detail = getattr(p, "source_detail", "") or ""
    job.remote = p.remote
    job.posted_at = p.posted_at
    from app.models import utcnow

    job.last_seen = utcnow()
    return job


def run_for_candidate(session: Session, candidate: Candidate, location: str = "Israel") -> dict:
    """Full run for one candidate. Persists jobs + matches, returns a summary."""
    from app import preferences as prefs_mod

    profile = candidate.profile
    prefs = candidate.preferences
    # per-skill years the user recorded via the gauge — lets the scorer weight
    # skills the candidate is strongest in
    profile["skill_experience"] = candidate.skill_experience
    profile["preferences"] = prefs
    # a desired target level steers the scorer's seniority alignment
    wanted_levels = prefs_mod.get_target_levels(prefs)
    # One wanted level is a clear statement of where they see themselves, so it
    # replaces the resume-derived seniority for scoring. Several levels are a
    # widening of the search, not a new self-assessment, so the resume's own
    # level is kept and the list is used only as a filter.
    if len(wanted_levels) == 1:
        profile["seniority"] = wanted_levels[0]
    postings = fetch_all(profile, location=location)

    shortlist = prefilter.rank(profile, postings, config.PREFILTER_TOP_N)
    log.info("prefiltered to %d jobs for scoring", len(shortlist))

    jobs_to_score = [p for p, _ in shortlist]
    scores = scorer.score_jobs(profile, jobs_to_score)

    # Region/remote are soft *preferences*: give matching jobs a ranking boost
    # rather than dropping the rest — so a search never comes back empty.
    for (posting, _pre), score in zip(shortlist, scores):
        boost = prefs_mod.preference_boost(posting, prefs) * 100
        if boost:
            score["score"] = round(min(100.0, score["score"] + boost), 1)

    scored_pairs = list(zip(jobs_to_score, scores))
    # Rank everything, then keep matches above the floor — but always at least
    # MIN_RESULTS of the best ones, so a real resume never yields zero jobs.
    from app.matching import roles
    from app.matching.heuristic_scorer import detect_seniority
    from app.resume.heuristic import _lc

    cand_level = profile.get("seniority", "mid")
    target_level = wanted_levels
    cand_fams = roles.candidate_families(profile)

    ranked = sorted(zip(shortlist, scores), key=lambda x: x[1]["score"], reverse=True)
    kept = 0
    for i, ((posting, pre_score), score) in enumerate(ranked):
        # #1 only Israel-based or fully-remote roles
        if not prefs_mod.allowed_location(posting):
            continue
        # don't offer off-field roles (e.g. Sales / HR / Support to an engineer)
        if roles.alignment(cand_fams, roles.job_family(posting)) < 0.3:
            continue
        # #4/#5 don't offer roles at an unrealistic level (e.g. team-lead to a mid).
        # Detect the job's level from its TITLE — the description often name-drops
        # "senior"/"lead" for unrelated reasons.
        job_level = detect_seniority(_lc(posting.title))
        if prefs_mod.level_mismatch(job_level, cand_level, target_level):
            continue
        if score["score"] < config.MIN_SCORE_TO_SHOW and kept >= config.MIN_RESULTS:
            break
        job = _upsert_job(session, posting)
        session.flush()  # ensure job.id

        match = session.scalar(
            select(Match).where(Match.candidate_id == candidate.id, Match.job_id == job.id)
        )
        if match is None:
            match = Match(candidate_id=candidate.id, job_id=job.id)
            session.add(match)
        match.score = score["score"]
        match.prefilter_score = pre_score
        match.verdict = score["verdict"]
        match.why_json = json.dumps(score["why"], ensure_ascii=False)
        match.gaps_json = json.dumps(score["gaps"], ensure_ascii=False)
        kept += 1

    gaps = scorer.gap_analysis(profile, scored_pairs)
    summary = {
        "raw_postings": len(postings),
        "scored": len(jobs_to_score),
        "matches_kept": kept,
        "engine": profile.get("_engine", "llm"),
    }
    candidate.gap_analysis_json = json.dumps(gaps, ensure_ascii=False)
    candidate.last_summary_json = json.dumps(summary, ensure_ascii=False)
    session.commit()

    return {**summary, "gap_analysis": gaps}
