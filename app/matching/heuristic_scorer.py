"""Offline job scoring — rates a job 0-100 against a profile without any LLM.

Blends skill overlap, title match, and seniority alignment, and generates
human-readable why/gaps from the skills vocabulary. Used when no API key is set.
"""
from __future__ import annotations

from app.resume import skills_db
from app.resume.heuristic import _contains, _lc, detect_seniority
from app.sources.base import JobPosting

_SENIORITY_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "manager": 5, "director": 6}


def _skills_in(text_lc: str) -> set[str]:
    return {
        canonical
        for canonical, aliases in skills_db.SKILLS.items()
        if any(_contains(text_lc, a) for a in aliases)
    }


def _candidate_skills_in_job(profile_skills: list[str], job_lc: str) -> list[str]:
    """Every candidate skill the job mentions — vocabulary aliases OR the skill
    token itself, so custom skills (dbt, Looker, NestJS) count too."""
    present: list[str] = []
    for s in profile_skills:
        aliases = skills_db.SKILLS.get(s, [s])
        if any(_contains(job_lc, a) for a in aliases) or _contains(job_lc, s):
            present.append(s)
    return present


def score_one(profile: dict, job: JobPosting) -> dict:
    from app.matching import roles

    profile_skills = list(profile.get("skills", []))
    job_lc = _lc(f"{job.title} {job.description} {job.location}")
    title_lc = _lc(job.title)
    job_skills = _skills_in(job_lc)

    # role-family alignment (a backend dev should not be scored high for a TAM role)
    fam = roles.alignment(roles.candidate_families(profile), roles.job_family(job))

    # candidate skills present in the job (incl. custom skills) -> the core signal
    shared = _candidate_skills_in_job(profile_skills, job_lc)
    matched = len(shared)
    missing = sorted(job_skills - set(profile_skills))

    # 1) skill signal: strong overlap saturates (5+ shared skills = full marks)
    skill_signal = min(1.0, matched / 5.0)
    coverage = matched / max(3, len(job_skills)) if job_skills else skill_signal
    # being in exactly the same role family is itself a strong relevance signal,
    # even when the specific stack differs (Python backend vs Java backend)
    role_bonus = 0.12 if fam >= 1.0 else 0.0
    role_mult = 1.0 if fam >= 0.7 else fam  # only cross-field roles get multiplied down

    # 2) title alignment, in either language — a Hebrew ad for the candidate's
    # own role must earn the same bonus its English twin would
    from app.matching import bilingual

    own_titles = [t for t in profile.get("titles", []) if t]
    title_forms = own_titles + bilingual.expand_all(own_titles)
    title_hit = any(_contains(title_lc, t) for t in title_forms)
    skill_in_title = any(_contains(title_lc, a)
                         for s in shared for a in skills_db.SKILLS.get(s, [s]))
    title_bonus = 0.14 if title_hit else (0.08 if skill_in_title else 0.0)

    # 3) seniority alignment
    cand_level = _SENIORITY_RANK.get(profile.get("seniority", "mid"), 2)
    job_level = _SENIORITY_RANK.get(detect_seniority(title_lc), 2)
    gap = abs(cand_level - job_level)
    seniority_bonus = {0: 0.10, 1: 0.05}.get(gap, 0.0)

    # 4) experience weighting
    experience = profile.get("skill_experience") or {}
    deep_skills = [s for s in shared if experience.get(s, 0) >= 3]
    exp_bonus = min(0.10, 0.025 * len(deep_skills)) if experience else 0.0

    # 5) education signal: a relevant technical degree helps eng roles a little
    edu_bonus = 0.05 if (profile.get("education_technical") and (job_skills & _skills_in(title_lc) or title_hit)) else 0.0

    base = (0.50 * skill_signal + 0.12 * min(1.0, coverage) + role_bonus
            + title_bonus + seniority_bonus + exp_bonus + edu_bonus)
    score = round(max(0.0, min(1.0, base)) * role_mult * 100, 1)

    why: list[str] = []
    if shared:
        why.append("Matching skills: " + ", ".join(shared[:6]))
    if deep_skills:
        top = max(deep_skills, key=lambda s: experience.get(s, 0))
        why.append(f"Strong experience match: {top} ({experience[top]}y)")
    if title_hit:
        why.append("Job title matches your target roles")
    if gap == 0:
        why.append(f"Seniority fits your level ({profile.get('seniority', 'mid')})")
    if edu_bonus:
        why.append("Your degree fits this field")

    gaps: list[str] = []
    if fam < 0.5:
        gaps.append("Different field from your background")
    if missing:
        gaps.append("Job also mentions: " + ", ".join(missing[:5]))

    return {"score": score, "verdict": _verdict(score), "why": why[:4], "gaps": gaps[:3]}


def _verdict(score: float) -> str:
    if score >= 80:
        return "Excellent fit for your profile."
    if score >= 60:
        return "Strong match worth a look."
    if score >= 40:
        return "Partial match, some overlap."
    return "Weak match."


def score_jobs(profile: dict, jobs: list[JobPosting]) -> list[dict]:
    return [score_one(profile, j) for j in jobs]
