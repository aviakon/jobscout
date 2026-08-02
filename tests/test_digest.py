"""Digest logic: first run surfaces matches, second run (no new jobs) surfaces none."""
import json

from app.digest import collect_new_matches, run_digest
from app.models import Candidate, Job, Match, utcnow


def _mk_candidate(session):
    prof = {"skills": ["Python"], "titles": ["Backend Engineer"], "headline": "Backend Engineer"}
    c = Candidate(name="Tester", resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps(prof))
    session.add(c)
    session.flush()
    return c


def _mk_match(session, candidate, key, score, notified=False):
    j = Job(dedupe_key=key, title="Backend Engineer", company="Co", source="test", description="Python")
    session.add(j)
    session.flush()
    m = Match(candidate_id=candidate.id, job_id=j.id, score=score,
              notified_at=utcnow() if notified else None)
    session.add(m)
    session.flush()
    return m


def test_collect_new_matches_respects_threshold_and_notified(sqlite_session):
    c = _mk_candidate(sqlite_session)
    _mk_match(sqlite_session, c, "a", 90, notified=False)   # new, high  -> included
    _mk_match(sqlite_session, c, "b", 40, notified=False)   # new, low   -> excluded (below 60)
    _mk_match(sqlite_session, c, "c", 95, notified=True)    # old        -> excluded
    sqlite_session.commit()

    new = collect_new_matches(sqlite_session, c)
    assert len(new) == 1
    assert new[0].job.dedupe_key == "a"


def test_run_digest_marks_notified_so_second_run_is_empty(sqlite_session):
    c = _mk_candidate(sqlite_session)
    _mk_match(sqlite_session, c, "a", 90)
    _mk_match(sqlite_session, c, "b", 80)
    sqlite_session.commit()

    first = run_digest(sqlite_session, c, rescan=False, mark=True)
    assert first["count"] == 2

    second = run_digest(sqlite_session, c, rescan=False, mark=True)
    assert second["count"] == 0  # already acknowledged
