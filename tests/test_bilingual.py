"""Hebrew and English have to reach each other.

Israeli ads for one role appear as "AI Engineer" on one board and
"מהנדס בינה מלאכותית" on another. A candidate must find both, whichever
language their resume happens to be in.
"""
from app.matching import bilingual, prefilter, roles
from app.matching.heuristic_scorer import score_one
from app.sources.base import JobPosting


def _job(title, description="", location="תל אביב"):
    return JobPosting(title=title, company="חברה", source="test",
                      location=location, description=description, url="https://example.com/j")


AI_PROFILE = {"headline": "AI Engineer", "titles": ["AI Engineer"],
              "skills": ["Python", "Machine Learning"], "seniority": "senior"}


# --- the glossary ------------------------------------------------------------

def test_ai_maps_to_the_hebrew_term():
    assert "בינה מלאכותית" in bilingual.counterparts("ai")
    assert "בינה מלאכותית" in bilingual.counterparts("artificial intelligence")


def test_the_mapping_works_in_both_directions():
    assert "ai" in bilingual.counterparts("בינה מלאכותית")
    assert "machine learning" in bilingual.counterparts("למידת מכונה")


def test_a_phrase_expands_through_its_parts():
    """"Senior AI Engineer" was never translated as a whole, but each part was."""
    out = bilingual.expand("Senior AI Engineer")
    assert "בינה מלאכותית" in out
    assert "מהנדס" in out
    assert "בכיר" in out


def test_an_unknown_term_expands_to_nothing():
    assert bilingual.expand("Kubernetes wizardry") == []
    assert bilingual.expand("") == []


# --- the prefilter, which decides what even gets scored ----------------------

def test_an_english_profile_reaches_a_hebrew_posting():
    bag = prefilter.profile_terms(AI_PROFILE)
    hebrew_ad = _job("מהנדס בינה מלאכותית", "פיתוח מודלים, למידת מכונה, פייתון")
    assert prefilter.prefilter_score(bag, hebrew_ad) > 20


def test_a_hebrew_profile_reaches_an_english_posting():
    profile = {"headline": "מהנדס בינה מלאכותית", "titles": ["מהנדס בינה מלאכותית"],
               "skills": ["Python"], "seniority": "senior"}
    bag = prefilter.profile_terms(profile)
    english_ad = _job("AI Engineer", "Python, machine learning models", location="Tel Aviv")
    assert prefilter.prefilter_score(bag, english_ad) > 20


def test_off_field_hebrew_roles_are_still_rejected():
    """Widening the net must not start matching sales roles to an engineer."""
    bag = prefilter.profile_terms(AI_PROFILE)
    for title in ("מנהל מכירות", "מגייסת טכנולוגית", "מנהל כספים"):
        ad = _job(title, "ניהול צוות")
        assert prefilter.prefilter_score(bag, ad) == 0, title
        assert score_one(AI_PROFILE, ad)["score"] < 10, title


# --- role families -----------------------------------------------------------

def test_hebrew_titles_land_in_the_right_family():
    cases = {
        "מהנדס בינה מלאכותית": "ml",
        "מפתח בק אנד": "backend",
        "מדען נתונים": "data",
        "מהנדס סייבר": "security",
        "ראש צוות פיתוח": "management",
        "מנהל מכירות": "sales",
    }
    for title, family in cases.items():
        assert family in roles.families_of(title), f"{title} -> {roles.families_of(title)}"


def test_an_ai_candidate_is_aligned_with_a_hebrew_ai_job():
    fams = roles.candidate_families(AI_PROFILE)
    assert roles.alignment(fams, roles.job_family(_job("מהנדס בינה מלאכותית"))) == 1.0
    assert roles.alignment(fams, roles.job_family(_job("מנהל מכירות"))) < 0.3


# --- scoring parity ----------------------------------------------------------

def test_a_hebrew_ad_is_not_penalised_for_its_language():
    """The same job in Hebrew and English should score in the same league."""
    hebrew = score_one(AI_PROFILE, _job("מהנדס בינה מלאכותית בכיר",
                                        "פיתוח מודלים בפייתון, למידת מכונה"))["score"]
    english = score_one(AI_PROFILE, _job("Senior AI Engineer",
                                         "Python, machine learning", location="Tel Aviv"))["score"]
    assert hebrew > 40, hebrew
    assert hebrew >= english * 0.6, f"hebrew {hebrew} vs english {english}"


def test_ai_is_recognised_as_a_skill_at_all():
    from app.resume.heuristic import _lc, extract_skills

    assert "AI" in extract_skills(_lc("Experienced AI engineer building LLM products"))
    assert "AI" in extract_skills(_lc("מהנדס בינה מלאכותית עם ניסיון"))


def test_hebrew_prefixes_do_not_hide_a_match():
    """Hebrew glues ו/ב/ל/ה onto the next word, so "machine learning" appears as
    "ולמידת מכונה" and "Python" as "בפייתון". Plain boundary matching misses both."""
    from app.resume.heuristic import _lc, extract_skills

    found = extract_skills(_lc("דרוש מהנדס לבינה מלאכותית עם ניסיון בפייתון ולמידת מכונה"))
    assert {"AI", "Python", "Machine Learning"} <= set(found), found


def test_the_prefix_rule_does_not_invent_matches():
    """"מבינה" means "understands"; it must not read as מ + בינה."""
    from app.resume.heuristic import _lc, extract_skills

    assert "AI" not in extract_skills(_lc("היא מבינה את הבעיה ולא צריכה עזרה"))


def test_the_skill_vocabulary_has_no_duplicate_keys():
    """A repeated key silently overwrites the earlier one and drops its aliases."""
    import re

    with open("app/resume/skills_db.py", encoding="utf-8") as f:
        keys = re.findall(r'^    "([^"]+)":', f.read(), re.M)
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]


def test_ai_does_not_fire_inside_ordinary_words():
    """A two letter alias is the classic false positive; boundaries must hold."""
    from app.resume.heuristic import _lc, extract_skills

    found = extract_skills(_lc("Email maintenance and training available for retail staff"))
    assert "AI" not in found


# --- query expansion for search driven sources -------------------------------

def test_queries_go_out_in_both_languages():
    from app import preferences as prefs_mod

    out = prefs_mod.augment_queries(["AI Engineer"], {"roles": ["Data Scientist"]})
    assert "AI Engineer" in out and "Data Scientist" in out
    assert any("בינה מלאכותית" in q for q in out)
    assert any("מדען נתונים" in q for q in out)
