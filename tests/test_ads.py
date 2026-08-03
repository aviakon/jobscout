"""Sponsored slots: paid ads on top, house ad when a slot is unsold, and a hard
line between paid placement and genuine ranked matches.
"""
import json

import pytest

from app import ads, config
from app.models import Candidate, Job, Match


@pytest.fixture
def sponsors_file(tmp_path, monkeypatch):
    """Point the loader at a temp sponsors file and return a writer for it."""
    path = tmp_path / "sponsors.yaml"
    path.write_text("sponsors: []", encoding="utf-8")
    monkeypatch.setattr(config, "SPONSORS_FILE", path)

    def write(yaml_text: str):
        path.write_text(yaml_text, encoding="utf-8")

    return write


def test_unsold_slots_show_the_contact_invitation(sponsors_file):
    slots = ads.slots_for()
    assert len(slots) == config.AD_SLOTS
    assert all(a.is_house_ad for a in slots)
    assert config.CONTACT_EMAIL in slots[0].body
    assert slots[0].url.startswith("mailto:")


def test_a_paid_ad_takes_the_first_slot(sponsors_file):
    sponsors_file("""
sponsors:
  - slug: acme
    title: מחפשים מפתחי Backend
    company: Acme
    url: https://acme.example.com
""")
    slots = ads.slots_for()
    assert slots[0].slug == "acme"
    assert slots[0].paid is True
    assert slots[1].is_house_ad          # second slot still for sale
    assert len(slots) == config.AD_SLOTS


def test_paused_and_expired_ads_do_not_show(sponsors_file):
    sponsors_file("""
sponsors:
  - slug: paused
    title: מודעה מושהית
    active: false
  - slug: expired
    title: מודעה שפגה
    ends_on: 2020-01-01
  - slug: future
    title: מודעה עתידית
    starts_on: 2099-01-01
""")
    assert all(a.is_house_ad for a in ads.slots_for())


def test_targeted_ads_only_reach_a_matching_profile(sponsors_file):
    sponsors_file("""
sponsors:
  - slug: devops-only
    title: דרוש DevOps
    roles: [devops]
""")
    backend = {"headline": "Backend Developer", "titles": ["Backend Developer"], "skills": []}
    devops = {"headline": "DevOps Engineer", "titles": ["DevOps Engineer"], "skills": []}

    assert ads.slots_for(backend)[0].is_house_ad
    assert ads.slots_for(devops)[0].slug == "devops-only"


def test_an_untargeted_ad_reaches_everyone(sponsors_file):
    sponsors_file("""
sponsors:
  - slug: everyone
    title: מודעה לכולם
""")
    assert ads.slots_for({"headline": "Anything"})[0].slug == "everyone"


def test_a_broken_sponsors_file_does_not_break_the_page(sponsors_file):
    sponsors_file("sponsors: [ this is not: valid: yaml")
    slots = ads.slots_for()
    assert len(slots) == config.AD_SLOTS
    assert all(a.is_house_ad for a in slots)


# --- the integrity line -----------------------------------------------------

def _candidate_with_match(session):
    c = Candidate(name="Tester", resume_filename="t.txt", resume_text="x",
                  profile_json=json.dumps({"skills": ["Python"], "seniority": "mid"}))
    session.add(c)
    session.flush()
    j = Job(dedupe_key="d-ads", title="Backend Engineer", company="RealCo", source="test",
            description="Python", url="https://example.com/j")
    session.add(j)
    session.flush()
    session.add(Match(candidate_id=c.id, job_id=j.id, score=88, why_json="[]", gaps_json="[]"))
    session.commit()
    return c


def test_ads_are_labelled_and_kept_out_of_the_match_list(client, sqlite_session, sponsors_file):
    sponsors_file("""
sponsors:
  - slug: acme
    title: מודעה של אקמי
    company: Acme
    url: https://acme.example.com
""")
    c = _candidate_with_match(sqlite_session)
    page = client.get(f"/candidate/{c.public_id}").text

    assert "ממומן" in page                      # every slot carries the label
    assert "מודעה של אקמי" in page

    # the ad must sit before the match list and never inside it: an ad that can
    # be sorted/filtered like a match would read as a real ranked result
    assert page.index("ad-strip") < page.index('id="matches-list"')
    match_list = page.split('id="matches-list"', 1)[1]
    assert "ad-card" not in match_list
    assert "acme.example.com" not in match_list


def test_sponsored_links_carry_the_sponsored_rel(client, sqlite_session, sponsors_file):
    sponsors_file("""
sponsors:
  - slug: acme
    title: מודעה
    url: https://acme.example.com
""")
    c = _candidate_with_match(sqlite_session)
    page = client.get(f"/candidate/{c.public_id}").text
    assert 'rel="noopener sponsored"' in page  # honest to search engines too


def test_match_stats_ignore_the_ads(client, sqlite_session, sponsors_file):
    sponsors_file("""
sponsors:
  - slug: acme
    title: מודעה
""")
    c = _candidate_with_match(sqlite_session)
    page = client.get(f"/candidate/{c.public_id}").text
    assert "משרות מתאימות <span class=\"muted\">(1)</span>" in page  # 1 match, not 3
