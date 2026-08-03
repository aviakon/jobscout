"""The author credit has to appear on every page, not just the ones we remember."""
import json

import pytest

from app import config
from app.models import Candidate, Job, Match


@pytest.fixture
def pages(client, sqlite_session):
    """One URL per page template the site can render."""
    c = Candidate(name="Tester", resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps({"skills": ["Python"], "seniority": "mid"}))
    sqlite_session.add(c)
    sqlite_session.flush()
    j = Job(dedupe_key="d-foot", title="Backend Engineer", company="Co", source="test",
            description="Python", url="https://example.com/j")
    sqlite_session.add(j)
    sqlite_session.flush()
    m = Match(candidate_id=c.id, job_id=j.id, score=70, why_json="[]", gaps_json="[]")
    sqlite_session.add(m)
    sqlite_session.commit()

    return client, [
        "/",                                              # landing
        "/start",                                         # onboarding
        f"/candidate/{c.public_id}",                      # results
        f"/candidate/{c.public_id}/digest",               # digest
        f"/candidate/{c.public_id}/match/{m.id}/cover-letter",
    ]


def test_every_page_credits_the_author(pages):
    client, urls = pages
    for url in urls:
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert config.SITE_AUTHOR in resp.text, f"missing credit on {url}"


def test_every_page_offers_the_advertising_contact(pages):
    client, urls = pages
    for url in urls:
        assert config.CONTACT_EMAIL in client.get(url).text, f"missing contact on {url}"


def test_the_stats_dashboard_is_credited_too(client, monkeypatch):
    monkeypatch.setattr(config, "stats_key", lambda: "k")
    assert config.SITE_AUTHOR in client.get("/stats/k").text
