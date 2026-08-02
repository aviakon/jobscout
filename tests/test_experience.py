"""Tests for deep resume experience analysis + level/location filters."""
from app import preferences as prefs_mod
from app.resume import experience
from app.resume.heuristic import build_profile
from app.sources.base import JobPosting

SHACHAR = """SHACHAR MARGALIT
Backend Team Lead

Unit 8200 - Backend Developer   2023 - 2026
- Developed backend services using Python and TypeScript.
- Built APIs using FastAPI. Worked with Docker and Kubernetes.

IDF - Combat Commander & Operations Officer   2020 - 2023
- Commanded soldiers and led training as a team lead.
"""

CIVILIAN_LEAD = """Alex Kim
Engineering Team Lead

Acme Corp - Engineering Team Lead   2019 - 2025
- Led a team of 8 engineers building services in Python and Go.
"""


def test_durations_from_date_ranges():
    ents = experience.parse_experiences(SHACHAR)
    dev = next(e for e in ents if "Developer" in e["title"])
    assert dev["years"] == 3.0
    assert dev["is_military"] is True and dev["is_tech"] is True


def test_military_leadership_does_not_make_lead():
    p = build_profile(SHACHAR)
    assert p["seniority"] == "mid"          # not "lead" — army team-lead is discounted (#5)


def test_sustained_civilian_lead_is_recognized():
    p = build_profile(CIVILIAN_LEAD)
    assert p["seniority"] in ("lead", "manager")


def test_per_skill_years_from_role_dates():
    p = build_profile(SHACHAR)
    # Python used in the 2023-2026 role -> ~3 years
    assert p["skill_years"].get("Python") == 3


def test_level_mismatch_blocks_teamlead_for_mid():
    assert prefs_mod.level_mismatch("lead", "mid") is True       # team-lead to a mid -> block (#4)
    assert prefs_mod.level_mismatch("senior", "mid") is False    # one step up is fine
    assert prefs_mod.level_mismatch("manager", "mid") is True
    assert prefs_mod.level_mismatch("lead", "mid", target_level="lead") is False  # explicit target


def _job(loc, remote=""):
    return JobPosting(title="Backend Engineer", company="Co", source="t", description="", location=loc, remote=remote)


def test_education_parsed():
    from app.resume import experience
    edu = experience.parse_education("Education\nB.Sc. in Computer Science, Technion, 2019")
    assert edu and edu[0]["level"] == "bachelor"
    assert "Computer Science" in edu[0]["field"]
    assert experience.education_summary(edu)["is_technical"] is True


def test_no_phantom_degree():
    from app.resume import experience
    # 'Commander' / 'Margalit' must not trigger a master's degree
    edu = experience.parse_education("IDF - Combat Commander 2020 - 2023")
    assert edu == []


def test_role_family_alignment():
    from app.matching import roles
    assert roles.alignment({"backend"}, {"backend"}) == 1.0
    assert roles.alignment({"backend"}, {"devops"}) == 0.7        # adjacent
    assert roles.alignment({"backend"}, {"success"}) < 0.3        # TAM/support -> off-field
    assert roles.alignment({"backend"}, {"sales"}) < 0.3
    assert roles.job_family(JobPosting(title="Technical Account Manager", company="C", source="t", description="")) == {"success"}


def test_scorer_demotes_off_field_role():
    from app.matching import heuristic_scorer
    prof = build_profile(SHACHAR)
    backend = JobPosting(title="Backend Engineer", company="C", source="t",
                         description="Python, FastAPI, Docker, SQL, Kubernetes microservices.")
    tam = JobPosting(title="Technical Account Manager", company="C", source="t",
                     description="Manage customer relationships and onboarding.")
    sb = heuristic_scorer.score_one(prof, backend)["score"]
    st = heuristic_scorer.score_one(prof, tam)["score"]
    assert sb > 60 and st < 30 and sb > st


def test_location_filter_israel_and_remote_only():
    assert prefs_mod.allowed_location(_job("Tel Aviv, Israel")) is True
    assert prefs_mod.allowed_location(_job("Herzliya")) is True
    assert prefs_mod.allowed_location(_job("", remote="Remote")) is True    # generic remote
    assert prefs_mod.allowed_location(_job("")) is True                     # unknown -> keep
    assert prefs_mod.allowed_location(_job("San Francisco")) is False       # foreign
    assert prefs_mod.allowed_location(_job("Remote - Japan")) is False      # foreign-pinned remote
    assert prefs_mod.allowed_location(_job("Sofia, Bulgaria")) is False
