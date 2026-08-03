"""The optional JSearch aggregator: the only lawful free route to Hebrew ads.

It is off until RAPIDAPI_KEY is set, so these tests pin the two things that
decide whether it is usable the moment a key appears: it must stay inside the
free tier's request budget, and a Hebrew posting must survive the whole way
through to a scored match.
"""
import httpx
import pytest

from app import config, preferences as prefs_mod
from app.pipeline import build_queries
from app.sources.jsearch import JSearchConnector


# --- request budget ----------------------------------------------------------

def test_queries_stay_inside_the_request_budget():
    """Bilingual expansion tripled the query list; each one is a billed request."""
    profile = {"titles": ["Backend Engineer", "AI Engineer", "Data Scientist"],
               "headline": "Senior Backend Engineer",
               "preferences": {"roles": ["DevOps", "Machine Learning"]}}
    assert len(build_queries(profile)) <= config.JSEARCH_MAX_QUERIES


def test_each_query_keeps_its_own_translation():
    """Capping must not strip the first query's Hebrew form in favour of the
    second query's, which is what a naive append-then-truncate does."""
    queries = build_queries({"titles": ["AI Engineer"], "headline": "AI Engineer",
                             "preferences": {"roles": []}})
    assert queries[0] == "AI Engineer"
    assert "בינה מלאכותית" in queries


def test_generic_words_lose_to_specific_phrases():
    out = prefs_mod.augment_queries(["AI Engineer"], {"roles": []})
    assert out.index("בינה מלאכותית") < out.index("מהנדס")


def test_pages_default_to_one_billed_request():
    assert JSearchConnector(api_key="x").pages == config.JSEARCH_PAGES == 1


# --- the connector -----------------------------------------------------------

def test_it_stays_off_without_a_key():
    assert JSearchConnector(api_key="").fetch("anything") == []


_HEBREW_RESPONSE = {
    "data": [{
        "job_title": "מהנדס בינה מלאכותית",
        "employer_name": "חברת הייטק",
        "job_city": "תל אביב", "job_country": "IL",
        "job_description": "דרוש מהנדס בינה מלאכותית עם ניסיון בפייתון ולמידת מכונה.",
        "job_apply_link": "https://example.co.il/job/1",
        "job_publisher": "AllJobs",
        "job_posted_at_datetime_utc": "2026-08-01T00:00:00Z",
        "job_is_remote": False,
    }]
}


@pytest.fixture
def hebrew_api(monkeypatch):
    def fake_get(self, url, **kw):
        return httpx.Response(200, json=_HEBREW_RESPONSE,
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)


def test_a_hebrew_posting_is_parsed(hebrew_api):
    posts = JSearchConnector(api_key="test-key").fetch("בינה מלאכותית")
    assert len(posts) == 1
    job = posts[0]
    assert job.title == "מהנדס בינה מלאכותית"
    assert job.company == "חברת הייטק"
    assert "תל אביב" in job.location
    assert job.source_detail == "AllJobs"   # credited to the real publisher


def test_a_hebrew_posting_survives_the_israel_filter(hebrew_api):
    job = JSearchConnector(api_key="test-key").fetch("בינה מלאכותית")[0]
    assert prefs_mod.allowed_location(job) is True


def test_a_hebrew_posting_reaches_an_english_profile(hebrew_api):
    """End to end: Hebrew ad in, English resume, real match out."""
    from app.matching import prefilter, roles
    from app.matching.heuristic_scorer import score_one

    job = JSearchConnector(api_key="test-key").fetch("בינה מלאכותית")[0]
    profile = {"headline": "AI Engineer", "titles": ["AI Engineer"],
               "skills": ["Python", "Machine Learning"], "seniority": "senior"}

    assert prefilter.prefilter_score(prefilter.profile_terms(profile), job) > 20
    assert roles.alignment(roles.candidate_families(profile), roles.job_family(job)) == 1.0
    assert score_one(profile, job)["score"] > 40
