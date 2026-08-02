"""Unit tests for normalization, dedupe, and prefilter — no network or API keys."""
from app.matching import prefilter
from app.sources.base import JobPosting, dedupe


def _job(title, company, desc="", loc="", source="test"):
    return JobPosting(title=title, company=company, description=desc, location=loc, source=source)


def test_dedupe_collapses_same_job_across_sources():
    a = _job("Senior Backend Engineer", "Wiz Ltd", desc="short", source="greenhouse")
    b = _job("senior backend engineer", "Wiz", desc="a much longer description here", source="jsearch")
    c = _job("Frontend Engineer", "Wiz", source="lever")
    out = dedupe([a, b, c])
    assert len(out) == 2
    # keeps the longer description of the duplicate pair
    backend = [j for j in out if "backend" in j.title.lower()][0]
    assert backend.description == "a much longer description here"


def test_dedupe_key_ignores_company_suffix_and_case():
    a = _job("Data Scientist", "Acme Inc")
    b = _job("data scientist", "ACME")
    assert a.dedupe_key == b.dedupe_key


def test_prefilter_ranks_relevant_job_higher():
    profile = {
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "titles": ["Backend Engineer"],
        "industries": ["Fintech"],
        "headline": "Backend Engineer",
    }
    good = _job("Backend Engineer", "Co", desc="We use Python, FastAPI and PostgreSQL with Docker.")
    bad = _job("Graphic Designer", "Co", desc="Photoshop and Illustrator, brand design.")
    ranked = prefilter.rank(profile, [bad, good], top_n=2)
    assert ranked[0][0].title == "Backend Engineer"
    assert ranked[0][1] > ranked[1][1]


def test_prefilter_handles_hebrew_tokens():
    profile = {"skills": ["פייתון", "ריאקט"], "titles": ["מפתח"], "headline": "מפתח תוכנה"}
    job = _job("מפתח תוכנה", "חברה", desc="דרוש מפתח עם ניסיון בפייתון וריאקט")
    bag = prefilter.profile_terms(profile)
    assert prefilter.prefilter_score(bag, job) > 0
