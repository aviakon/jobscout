"""Security properties needed for a publicly-hosted, login-free deployment:
candidates are addressed by an unguessable token, one candidate's data can't
be reached through another candidate's + a guessed match id, and the
expensive scan endpoints are rate-limited.
"""
import json

from app.models import Candidate, Job, Match


def _candidate(session, name="Tester"):
    c = Candidate(name=name, resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps({"skills": ["Python"]}))
    session.add(c)
    session.flush()
    return c


def _match_for(session, candidate):
    j = Job(dedupe_key=f"job-{candidate.id}", title="Backend Engineer", company="Co",
            source="test", description="Python", url="https://example.com/j")
    session.add(j)
    session.flush()
    m = Match(candidate_id=candidate.id, job_id=j.id, score=80, why_json="[]", gaps_json="[]")
    session.add(m)
    session.commit()
    return m


def test_unknown_token_is_404(client):
    resp = client.get("/candidate/does-not-exist")
    assert resp.status_code == 404


def test_candidate_page_reachable_by_its_own_token(client, sqlite_session):
    c = _candidate(sqlite_session)
    resp = client.get(f"/candidate/{c.public_id}")
    assert resp.status_code == 200
    assert "Tester" in resp.text


def test_match_not_reachable_through_a_different_candidates_token(client, sqlite_session):
    owner = _candidate(sqlite_session, "Owner")
    stranger = _candidate(sqlite_session, "Stranger")
    match = _match_for(sqlite_session, owner)

    # the real owner can open their cover letter
    ok = client.get(f"/candidate/{owner.public_id}/match/{match.id}/cover-letter")
    assert ok.status_code == 200

    # a different (valid!) candidate token cannot reach that same match id
    blocked = client.get(f"/candidate/{stranger.public_id}/match/{match.id}/cover-letter")
    assert blocked.status_code == 404


def test_status_update_enforces_ownership(client, sqlite_session):
    owner = _candidate(sqlite_session, "Owner")
    stranger = _candidate(sqlite_session, "Stranger")
    match = _match_for(sqlite_session, owner)

    blocked = client.post(f"/candidate/{stranger.public_id}/match/{match.id}/status", data={"status": "saved"})
    assert blocked.status_code == 404

    ok = client.post(f"/candidate/{owner.public_id}/match/{match.id}/status", data={"status": "saved"})
    assert ok.status_code == 200


def test_landing_page_lists_nothing_without_a_cookie(client, sqlite_session):
    _candidate(sqlite_session, "SomeoneElse")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SomeoneElse" not in resp.text  # no global directory of every user's candidates


def test_search_endpoint_is_rate_limited(client, sqlite_session, monkeypatch):
    import app.main as main_module

    c = _candidate(sqlite_session)
    monkeypatch.setattr(main_module, "run_for_candidate", lambda *a, **k: {})

    codes = [client.post(f"/candidate/{c.public_id}/search", data={"location": "Israel"},
                         follow_redirects=False).status_code
             for _ in range(8)]
    assert 303 in codes  # some succeed
    assert 429 in codes  # eventually throttled
