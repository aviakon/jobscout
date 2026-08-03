"""Tests for search preferences: parsing, region logic, fit flags, query augmentation."""
import json

from app import preferences as prefs_mod
from app.main import _build_preferences
from app.models import Candidate
from app.sources.base import JobPosting


def test_build_preferences_parses_fields():
    p = _build_preferences("25,000", "center,sharon", "full", "remote", "senior", "Backend, Data")
    assert p["salary_min"] == 25000
    assert p["regions"] == ["center", "sharon"]
    assert p["employment_type"] == "full"
    assert p["remote"] == "remote"
    assert p["target_levels"] == ["senior"]
    assert p["roles"] == ["Backend", "Data"]


def test_several_wanted_levels_are_kept():
    p = _build_preferences("", "all", "any", "any", "mid,senior,lead", "")
    assert p["target_levels"] == ["mid", "senior", "lead"]


def test_no_wanted_level_means_no_constraint():
    p = _build_preferences("", "all", "any", "any", "", "")
    assert p["target_levels"] == []
    assert prefs_mod.get_target_levels(p) == []


def test_a_legacy_single_level_still_reads():
    """Profiles saved before multi-select stored a bare string."""
    assert prefs_mod.get_target_levels({"target_level": "senior"}) == ["senior"]
    assert prefs_mod.get_target_levels({"target_levels": ["mid", "lead"]}) == ["mid", "lead"]


def test_several_levels_widen_the_search_rather_than_narrow_it():
    """A job only has to suit one of the wanted levels."""
    # wanting mid or manager should accept a senior role (adjacent to mid)
    assert prefs_mod.level_mismatch("senior", "mid", ["mid", "manager"]) is False
    # ... and a lead role (adjacent to manager)
    assert prefs_mod.level_mismatch("lead", "mid", ["mid", "manager"]) is False
    # an intern role suits neither
    assert prefs_mod.level_mismatch("intern", "mid", ["senior", "manager"]) is True


def test_level_matches_accepts_a_list():
    assert prefs_mod.level_matches("senior", ["junior", "senior"]) is True
    assert prefs_mod.level_matches("intern", ["senior"]) is False
    assert prefs_mod.level_matches("senior", []) is None


def test_build_preferences_all_means_no_constraint():
    p = _build_preferences("", "all", "any", "any", "", "")
    assert p["regions"] == []
    assert p["salary_min"] is None


def test_region_matches_center_and_other():
    assert prefs_mod.region_matches("Tel Aviv, Israel", "center") is True
    assert prefs_mod.region_matches("Haifa", "center") is False   # clearly north
    assert prefs_mod.region_matches("", "center") is None          # unknown


def test_region_fit_multi_region():
    prefs = {"regions": ["center", "north"]}
    assert prefs_mod.region_fit("Tel Aviv", prefs) is True         # matches center
    assert prefs_mod.region_fit("Haifa", prefs) is True            # matches north
    assert prefs_mod.region_fit("Beer Sheva", prefs) is False      # south, neither
    assert prefs_mod.region_fit("Remote", prefs) is None           # unknown
    assert prefs_mod.region_fit("Beer Sheva", {"regions": []}) is None  # no constraint


def test_region_never_hard_excludes_via_boost():
    # region is a soft boost, not a filter — out-of-region jobs still score
    job = JobPosting(title="Backend", company="Co", source="t", description="", location="Beer Sheva")
    assert prefs_mod.preference_boost(job, {"regions": ["center"]}) == 0.0  # no boost, but not dropped
    infit = JobPosting(title="Backend", company="Co", source="t", description="", location="Ramat Gan")
    assert prefs_mod.preference_boost(infit, {"regions": ["center"]}) > 0.0


def test_fit_flags_multi_region():
    job = JobPosting(title="Backend", company="Co", source="test",
                     description="", location="Herzliya", remote="remote")
    flags = prefs_mod.fit_flags(job, {"regions": ["center"], "remote": "remote"})
    assert any("אזור" in f for f in flags)
    assert any("מהבית" in f for f in flags)


def test_legacy_single_region_still_read():
    assert prefs_mod.get_regions({"region": "center"}) == ["center"]
    assert prefs_mod.get_regions({"region": "all"}) == []


def test_augment_queries_adds_roles():
    out = prefs_mod.augment_queries(["software engineer"], {"roles": ["Data Engineer", "DevOps"]})
    assert "software engineer" in out and "Data Engineer" in out and "DevOps" in out


def test_preferences_persist_on_candidate(sqlite_session):
    c = Candidate(name="T", resume_filename="t", resume_text="x",
                  profile_json="{}", preferences_json=json.dumps({"regions": ["center"], "roles": ["Backend"]}))
    sqlite_session.add(c)
    sqlite_session.commit()
    assert sqlite_session.get(Candidate, c.id).preferences["regions"] == ["center"]
