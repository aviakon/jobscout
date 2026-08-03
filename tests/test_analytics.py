"""Usage analytics: it must count real activity, stay private, and stay locked.

The dashboard is the only place the numbers exist, and the site has no login,
so the access rules here matter as much as the counting.
"""
import json

import pytest
from sqlalchemy import select

from app import analytics, config
from app.models import Candidate, Visit


@pytest.fixture
def stats_key(monkeypatch):
    monkeypatch.setattr(config, "stats_key", lambda: "test-secret-key")
    return "test-secret-key"


def _candidate(session):
    c = Candidate(name="Tester", resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps({"skills": ["Python"]}))
    session.add(c)
    session.commit()
    return c


# --- counting ---------------------------------------------------------------

def test_a_page_view_is_recorded(client, sqlite_session):
    client.get("/")
    visits = sqlite_session.scalars(select(Visit).where(Visit.kind == "page")).all()
    assert len(visits) == 1
    assert visits[0].path == "/"


def test_assets_and_health_checks_are_not_counted(client, sqlite_session):
    client.get("/healthz")
    client.get("/static/style.css")
    assert sqlite_session.scalars(select(Visit)).all() == []


def test_the_dashboard_does_not_count_itself(client, sqlite_session, stats_key):
    client.get(f"/stats/{stats_key}")
    assert sqlite_session.scalars(select(Visit).where(Visit.kind == "page")).all() == []


def test_ad_clicks_are_recorded(client, sqlite_session):
    assert client.post("/ad/acme/click").status_code == 204
    visit = sqlite_session.scalar(select(Visit).where(Visit.kind == "ad_click"))
    assert visit is not None and visit.label == "acme"


def test_the_summary_adds_up(client, sqlite_session, stats_key):
    for _ in range(3):
        client.get("/")
    s = analytics.summary(sqlite_session)
    assert s["today"]["views"] == 3
    assert s["today"]["visitors"] == 1      # same client, counted once
    assert len(s["series"]) == 30           # zero-filled month


# --- privacy ----------------------------------------------------------------

def test_no_ip_address_or_user_agent_is_stored(client, sqlite_session):
    client.get("/", headers={"X-Forwarded-For": "203.0.113.9", "User-Agent": "SecretBrowser/1.0"})
    visit = sqlite_session.scalar(select(Visit))
    stored = " ".join(str(getattr(visit, c)) for c in
                      ("path", "visitor", "referrer", "label", "day", "kind"))
    assert "203.0.113.9" not in stored
    assert "SecretBrowser" not in stored
    assert len(visit.visitor) == 32          # an opaque hash, not an identifier


def test_different_visitors_are_told_apart(client, sqlite_session):
    client.get("/", headers={"X-Forwarded-For": "203.0.113.1"})
    client.get("/", headers={"X-Forwarded-For": "203.0.113.2"})
    assert analytics.summary(sqlite_session)["today"]["visitors"] == 2


def test_referrer_query_strings_are_dropped(client, sqlite_session):
    client.get("/", headers={"Referer": "https://news.example.com/post?utm_user=personal-data"})
    visit = sqlite_session.scalar(select(Visit))
    assert visit.referrer == "https://news.example.com/post"


# --- access -----------------------------------------------------------------

def test_the_dashboard_is_hidden_without_a_key(client, monkeypatch):
    monkeypatch.setattr(config, "stats_key", lambda: "")
    assert client.get("/stats/anything").status_code == 404


def test_a_wrong_key_is_indistinguishable_from_a_missing_page(client, stats_key):
    assert client.get("/stats/not-the-key").status_code == 404


def test_the_right_key_opens_the_dashboard(client, sqlite_session, stats_key):
    _candidate(sqlite_session)
    resp = client.get(f"/stats/{stats_key}")
    assert resp.status_code == 200
    assert "נתוני שימוש" in resp.text


def test_a_key_is_generated_and_then_reused(tmp_path, monkeypatch):
    """The dashboard must work with no manual setup, and keep the same URL
    across restarts so a bookmark does not rot."""
    monkeypatch.delenv("STATS_KEY", raising=False)
    monkeypatch.setattr(config, "STATS_KEY_FILE", tmp_path / ".stats_key")

    first = config.stats_key()
    assert len(first) > 20            # unguessable
    assert config.stats_key() == first  # stable across boots


def test_an_explicit_key_wins_over_the_generated_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATS_KEY_FILE", tmp_path / ".stats_key")
    monkeypatch.setenv("STATS_KEY", "chosen-by-hand")
    assert config.stats_key() == "chosen-by-hand"


def test_analytics_never_breaks_a_page(client, sqlite_session, monkeypatch):
    """A failing analytics write must not take the page down with it."""
    def boom(*a, **k):
        raise RuntimeError("db is gone")

    monkeypatch.setattr(analytics, "visitor_id", boom)
    assert client.get("/").status_code == 200
