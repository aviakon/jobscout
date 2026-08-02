"""Tests for adding/removing skills on a candidate profile."""
import json

from app.main import add_skill, remove_skill
from app.models import Candidate


def _candidate(session):
    c = Candidate(
        name="Tester", resume_filename="t.txt", resume_text="x",
        profile_json=json.dumps({"skills": ["Python", "AWS"]}),
        skill_experience_json=json.dumps({"AWS": 5}),
    )
    session.add(c)
    session.flush()
    return c


def test_add_new_skill(sqlite_session):
    c = _candidate(sqlite_session)
    res = add_skill(c.public_id, skill="Rust", session=sqlite_session)
    assert res["added"] is True
    assert "Rust" in sqlite_session.get(Candidate, c.id).profile["skills"]


def test_add_is_case_insensitive_dedupe(sqlite_session):
    c = _candidate(sqlite_session)
    res = add_skill(c.public_id, skill="python", session=sqlite_session)
    assert res["added"] is False
    # still only one Python entry
    skills = sqlite_session.get(Candidate, c.id).profile["skills"]
    assert sum(1 for s in skills if s.lower() == "python") == 1


def test_add_custom_skill_is_trimmed(sqlite_session):
    c = _candidate(sqlite_session)
    add_skill(c.public_id, skill="  Rust Programming  ", session=sqlite_session)
    assert "Rust Programming" in sqlite_session.get(Candidate, c.id).profile["skills"]


def test_remove_skill_also_drops_experience(sqlite_session):
    c = _candidate(sqlite_session)
    remove_skill(c.public_id, skill="AWS", session=sqlite_session)
    fresh = sqlite_session.get(Candidate, c.id)
    assert "AWS" not in fresh.profile["skills"]
    assert "AWS" not in fresh.skill_experience


def test_public_id_is_generated_and_unguessable(sqlite_session):
    c = _candidate(sqlite_session)
    assert c.public_id and len(c.public_id) >= 16
    c2 = _candidate(sqlite_session)
    assert c.public_id != c2.public_id
