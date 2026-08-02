"""Tests for the offline (no-API-key) parser and scorer."""
from app.matching import heuristic_scorer
from app.resume import heuristic
from app.sources.base import JobPosting

SAMPLE = """Daniel Cohen
Senior Backend Engineer
8 years of experience building microservices in Python (FastAPI) on AWS and Kubernetes.
Worked with PostgreSQL, Redis and Kafka. Team lead responsibilities mentoring engineers.
Languages: Hebrew (native), English (fluent).
"""


def test_parser_extracts_core_skills():
    p = heuristic.build_profile(SAMPLE)
    for expected in ("Python", "FastAPI", "AWS", "Kubernetes", "PostgreSQL", "Kafka"):
        assert expected in p["skills"], f"{expected} missing from {p['skills']}"


def test_parser_detects_seniority_and_years():
    p = heuristic.build_profile(SAMPLE)
    assert p["seniority"] == "senior"
    assert p["total_years_experience"] == 8.0


def test_parser_detects_languages():
    p = heuristic.build_profile(SAMPLE)
    assert "Hebrew" in p["languages"] and "English" in p["languages"]


def test_listed_skills_beyond_vocabulary_are_added():
    text = (
        "Dana Cohen\nData Engineer\n\n"
        "Skills: Python, Airflow, dbt, Snowflake, Looker, Kubernetes\n"
    )
    p = heuristic.build_profile(text)
    # 'dbt' and 'Looker' are not in the vocabulary but are listed → captured verbatim
    assert "dbt" in p["skills"]
    assert "Looker" in p["skills"]
    assert p["titles"]  # 'Data Engineer' headline used as a target title


def test_space_stripped_pdf_skills_recovered():
    # simulate a PDF that lost its spaces (e.g. "SHACHARMARGALIT")
    normal = ("Backend Developer\nDeveloped services using Python and TypeScript. "
              "Built APIs with FastAPI and NestJS. Used Docker, Kubernetes and Elasticsearch.")
    stripped = "\n".join(line.replace(" ", "") for line in normal.splitlines())
    p = heuristic.build_profile(stripped)
    for expected in ("Python", "TypeScript", "FastAPI", "Docker"):
        assert expected in p["skills"], f"{expected} not recovered from {p['skills']}"
    assert "Scala" not in p["skills"]  # 'scalable'/'scala' false positive suppressed


def test_normal_text_still_precise():
    # when spaces are present, the lenient fallback must NOT fire false positives
    p = heuristic.build_profile("Experienced in building scalable, reactive systems with Python.")
    assert "Scala" not in p["skills"]
    assert "React" not in p["skills"]
    assert "Python" in p["skills"]


def test_no_false_positive_substrings():
    # "scalable" must not yield Scala; "building" must not yield UX/UI
    p = heuristic.build_profile("Experienced in building scalable web applications.")
    assert "Scala" not in p["skills"]
    assert "UX/UI" not in p["skills"]


def test_scorer_prefers_matching_backend_role():
    profile = heuristic.build_profile(SAMPLE)
    good = JobPosting(
        title="Senior Backend Engineer",
        company="Co", source="test",
        description="Python, FastAPI, Kubernetes, AWS, PostgreSQL microservices.",
    )
    bad = JobPosting(
        title="Graphic Designer", company="Co", source="test",
        description="Photoshop, Illustrator, brand and visual design.",
    )
    sg = heuristic_scorer.score_one(profile, good)
    sb = heuristic_scorer.score_one(profile, bad)
    assert sg["score"] > sb["score"]
    assert sg["score"] >= 60
    assert any("Python" in w or "Matching skills" in w for w in sg["why"])


def test_experience_boosts_matching_job_score():
    profile = heuristic.build_profile(SAMPLE)
    job = JobPosting(
        title="Backend Engineer", company="Co", source="test",
        description="Python, FastAPI, Kubernetes, AWS microservices.",
    )
    base = heuristic_scorer.score_one(profile, job)["score"]

    boosted_profile = dict(profile)
    boosted_profile["skill_experience"] = {"Python": 8, "AWS": 5, "Kubernetes": 4}
    boosted = heuristic_scorer.score_one(boosted_profile, job)
    assert boosted["score"] > base
    assert any("Strong experience match" in w for w in boosted["why"])


def test_scorer_reports_gaps():
    profile = heuristic.build_profile(SAMPLE)
    job = JobPosting(
        title="Backend Engineer", company="Co", source="test",
        description="Python and Go with Terraform and Azure on GCP.",
    )
    s = heuristic_scorer.score_one(profile, job)
    # Go / Azure / GCP are in the job but not the profile → should appear as gaps
    assert s["gaps"]
