"""Regression guard: no em-dash / en-dash in anything shown to the user.

Code comments, docstrings, log messages, and regexes that parse dashes OUT of
resume text are fine and intentionally excluded here — this only checks
rendered pages and generated user-facing strings.
"""
import json

from app.cover_letter import generate
from app.digest import render_digest_html, render_digest_text
from app.matching.heuristic_scorer import _verdict
from app.models import Candidate, Job, Match
from app.sources.base import JobPosting

DASHES = "—–"


def _no_dashes(text: str) -> bool:
    return not any(d in text for d in DASHES)


def test_landing_page_has_no_dashes(client):
    resp = client.get("/")
    assert _no_dashes(resp.text)


def test_onboarding_page_has_no_dashes(client):
    resp = client.get("/start")
    assert _no_dashes(resp.text)


def test_stats_dashboard_has_no_dashes(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "stats_key", lambda: "k")
    assert _no_dashes(client.get("/stats/k").text)


def test_candidate_page_has_no_dashes(client, sqlite_session):
    c = Candidate(name="Tester", resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps({"skills": ["Python"], "seniority": "mid"}))
    sqlite_session.add(c)
    sqlite_session.flush()
    j = Job(dedupe_key="d1", title="Backend Engineer", company="Co", source="test",
            description="Python", url="https://example.com/j")
    sqlite_session.add(j)
    sqlite_session.flush()
    sqlite_session.add(Match(candidate_id=c.id, job_id=j.id, score=55,
                             verdict=_verdict(55), why_json="[]", gaps_json="[]"))
    sqlite_session.commit()

    resp = client.get(f"/candidate/{c.public_id}")
    assert _no_dashes(resp.text)


def test_experience_title_dash_is_cleaned():
    from app.resume.experience import parse_experiences

    text = "Unit 8200 - Backend Developer   2020 - 2025\nDid stuff."
    entries = parse_experiences(text)
    assert entries and _no_dashes(entries[0]["title"])
    assert entries[0]["title"] == "Unit 8200, Backend Developer"


def test_all_verdict_strings_have_no_dashes():
    for score in (10, 45, 65, 85):
        assert _no_dashes(_verdict(score))


def test_cover_letters_have_no_dashes():
    profile = {"name": "Dana", "headline": "Backend Engineer", "seniority": "senior",
               "total_years_experience": 5, "skills": ["Python", "AWS"]}
    en_job = Job(title="Backend Engineer", company="Acme", source="test",
                description="Python and AWS needed.")
    he_job = Job(title="מהנדס תוכנה", company="חברה", source="test",
                description="דרוש ניסיון בפייתון.")
    for job in (en_job, he_job):
        result = generate(profile, job)
        assert _no_dashes(result["letter"])
        assert all(_no_dashes(t) for t in result["tweaks"])


def test_digest_render_has_no_dashes(sqlite_session):
    c = Candidate(name="Dana", resume_filename="t.txt", resume_text="x", profile_json="{}")
    sqlite_session.add(c)
    sqlite_session.flush()
    j = Job(dedupe_key="d2", title="Backend Engineer", company="Co", source="test",
            description="", url="https://example.com/j")
    sqlite_session.add(j)
    sqlite_session.flush()
    m = Match(candidate_id=c.id, job_id=j.id, score=70, verdict=_verdict(70),
              why_json=json.dumps(["Matching skills: Python"]), gaps_json="[]")
    sqlite_session.add(m)
    sqlite_session.commit()
    m.job = j  # relationship access used by the renderer

    from datetime import datetime, timezone
    digest = {"candidate": c, "new_matches": [m], "count": 1, "generated_at": datetime.now(timezone.utc)}
    assert _no_dashes(render_digest_html(digest))
    assert _no_dashes(render_digest_text(digest))
