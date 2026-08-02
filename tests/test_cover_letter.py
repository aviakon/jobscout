"""Tests for the offline cover-letter generator."""
from app.cover_letter import generate
from app.models import Job
from app.resume.heuristic import build_profile

PROFILE = build_profile(
    "Daniel Cohen\nSenior Backend Engineer\n8 years with Python, FastAPI, AWS, Kubernetes, PostgreSQL."
)


def _job(title="Senior Backend Engineer", company="Wiz", desc="Python, FastAPI, Kubernetes, AWS microservices."):
    return Job(title=title, company=company, location="Tel Aviv", source="greenhouse", description=desc)


def test_english_letter_mentions_company_and_matching_skills():
    r = generate(PROFILE, _job())
    assert r["engine"] == "heuristic" and r["lang"] == "en"
    assert "Wiz" in r["letter"]
    assert PROFILE["name"] in r["letter"]
    # at least one matching skill should appear in the letter
    assert any(sk in r["letter"] for sk in ("Python", "FastAPI", "AWS", "Kubernetes"))


def test_tweaks_are_actionable_and_include_title_mirror():
    r = generate(PROFILE, _job())
    assert r["tweaks"]
    assert any("Senior Backend Engineer" in t for t in r["tweaks"])


def test_hebrew_job_produces_hebrew_letter():
    job = _job(title="מהנדס תוכנה בכיר", company="חברה",
               desc="דרוש מפתח עם ניסיון ב-Python ו-Kubernetes לצוות הבקאנד שלנו.")
    r = generate(PROFILE, job)
    assert r["lang"] == "he"
    assert "חברה" in r["letter"]
    # contains Hebrew characters
    assert any("֐" <= ch <= "׿" for ch in r["letter"])


def test_no_invented_content_when_profile_empty():
    empty = {"skills": [], "titles": [], "name": ""}
    r = generate(empty, _job())
    assert r["letter"]  # still produces something graceful
    assert "[Your name]" in r["letter"]
