"""Job-origin tracking: every posting must be attributable to where it came from."""
from app import preferences as prefs_mod
from app.sources.base import JobPosting


class _Job:
    """Stand-in for the Job ORM row (only the fields the label logic reads)."""

    def __init__(self, source, source_detail=""):
        self.source = source
        self.source_detail = source_detail


def test_company_board_sources_get_friendly_labels():
    assert "Greenhouse" in prefs_mod.source_label(_Job("greenhouse"))
    assert "Lever" in prefs_mod.source_label(_Job("lever"))
    assert "SmartRecruiters" in prefs_mod.source_label(_Job("smartrecruiters"))


def test_aggregated_job_shows_original_publisher_not_the_aggregator():
    # the whole point: a LinkedIn posting must read "LinkedIn", not "jsearch"
    job = _Job("jsearch", source_detail="LinkedIn")
    assert prefs_mod.source_label(job) == "LinkedIn"
    assert prefs_mod.source_label(_Job("jsearch", "Indeed")) == "Indeed"


def test_aggregator_without_publisher_falls_back_gracefully():
    assert prefs_mod.source_label(_Job("jsearch")) == "אגרגטור משרות"
    assert prefs_mod.source_label(_Job("")) == "לא ידוע"


def test_company_board_flag():
    assert prefs_mod.source_is_company_board(_Job("greenhouse")) is True
    assert prefs_mod.source_is_company_board(_Job("smartrecruiters")) is True
    assert prefs_mod.source_is_company_board(_Job("jsearch")) is False


def test_job_posting_carries_source_detail():
    p = JobPosting(title="Backend Engineer", company="Co", source="jsearch",
                   source_detail="LinkedIn")
    assert p.source_detail == "LinkedIn"
    # default stays empty so company-board connectors need no changes
    assert JobPosting(title="t", company="c", source="greenhouse").source_detail == ""
