"""The "continue without a resume" path.

Someone with no resume ready can still search: the roles they type stand in for
the resume, and they sharpen the profile afterwards by adding skills by hand.
These tests pin the two things that make that honest — we never invent skills
the person did not claim, and changing the roles actually changes the search.

Each test uses its own X-Forwarded-For so the per-IP rate limiter on /onboard
does not leak between tests.
"""
import json

import pytest
from sqlalchemy import select

from app import preferences as prefs_mod
from app.models import Candidate


@pytest.fixture
def no_scan(monkeypatch):
    """Stub the scan — these tests are about the profile, not the job sources."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "run_for_candidate", lambda *a, **k: {})


def _ip(n):
    return {"X-Forwarded-For": f"10.0.0.{n}"}


# --- the derived profile ----------------------------------------------------

def test_roles_become_the_titles_and_headline():
    profile = prefs_mod.profile_from_preferences(
        {"roles": ["Backend Developer", "DevOps"], "target_level": "senior", "remote": "any"}
    )
    assert profile["titles"] == ["Backend Developer", "DevOps"]
    assert profile["headline"] == "Backend Developer"
    assert profile["seniority"] == "senior"
    assert profile["no_resume"] is True


def test_no_skills_are_invented():
    profile = prefs_mod.profile_from_preferences({"roles": ["Backend Developer"]})
    assert profile["skills"] == []
    assert profile["skill_years"] == {}
    assert profile["experiences"] == []
    assert profile["total_years_experience"] == 0


def test_derived_profile_still_drives_role_matching():
    """The roles alone must be enough for the off-field filter to work."""
    from app.matching import roles

    profile = prefs_mod.profile_from_preferences({"roles": ["Backend Developer"]})
    fams = roles.candidate_families(profile)
    assert "backend" in fams
    assert roles.alignment(fams, {"backend"}) == 1.0
    assert roles.alignment(fams, {"hr"}) < 0.3  # a recruiter role is still filtered out


# --- onboarding without a resume -------------------------------------------

def test_onboard_without_a_resume_creates_a_searchable_candidate(client, sqlite_session, no_scan):
    resp = client.post("/onboard", data={"resume_method": "none", "roles": "Backend Developer",
                                         "target_level": "senior"},
                       headers=_ip(1), follow_redirects=False)
    assert resp.status_code == 303

    candidate = sqlite_session.scalar(select(Candidate))
    assert candidate is not None
    assert candidate.resume_text == ""
    assert candidate.profile["no_resume"] is True
    assert candidate.profile["titles"] == ["Backend Developer"]
    assert resp.headers["location"] == f"/candidate/{candidate.public_id}"


def test_onboard_without_a_resume_needs_at_least_one_role(client, sqlite_session, no_scan):
    resp = client.post("/onboard", data={"resume_method": "none", "roles": ""}, headers=_ip(2))
    assert resp.status_code == 400
    assert "תפקיד אחד" in resp.text  # friendly HTML banner, not raw JSON
    assert sqlite_session.scalar(select(Candidate)) is None


def test_a_resume_less_profile_renders(client, sqlite_session, no_scan):
    """No experience/education sections to show, but the page must still work
    and offer the add-skill box that makes the next search better."""
    client.post("/onboard", data={"resume_method": "none", "roles": "Backend Developer"},
                headers=_ip(3), follow_redirects=False)
    candidate = sqlite_session.scalar(select(Candidate))

    page = client.get(f"/candidate/{candidate.public_id}")
    assert page.status_code == 200
    assert "Backend Developer" in page.text
    assert 'id="skill-search"' in page.text


def test_editing_roles_rebuilds_the_profile_but_keeps_added_skills(client, sqlite_session, no_scan):
    profile = prefs_mod.profile_from_preferences({"roles": ["Backend Developer"]})
    profile["skills"] = ["Python"]  # added by hand on the profile page
    candidate = Candidate(
        name="", resume_filename="", resume_text="",
        profile_json=json.dumps(profile, ensure_ascii=False),
        preferences_json=json.dumps({"roles": ["Backend Developer"]}, ensure_ascii=False),
    )
    sqlite_session.add(candidate)
    sqlite_session.commit()

    resp = client.post("/onboard", data={"candidate_id": candidate.public_id,
                                         "roles": "DevOps Engineer"},
                       headers=_ip(4), follow_redirects=False)
    assert resp.status_code == 303

    sqlite_session.refresh(candidate)
    assert candidate.profile["titles"] == ["DevOps Engineer"]  # search follows the new role
    assert candidate.profile["skills"] == ["Python"]           # the user's own work survives


def test_a_real_resume_still_parses_normally(client, sqlite_session, no_scan):
    """Regression guard: the resume-less branch must not swallow the normal path."""
    resp = client.post("/onboard", data={
        "resume_method": "text",
        "resume_text": "Dana Levi\nSenior Backend Engineer\nPython, Django, AWS, Docker\n"
                       "Backend Engineer at Acme (2019 - 2025)",
        "roles": "",
    }, headers=_ip(5), follow_redirects=False)
    assert resp.status_code == 303

    candidate = sqlite_session.scalar(select(Candidate))
    assert candidate.profile.get("no_resume") is None
    assert candidate.profile["skills"]  # parsed from the resume, not from roles
