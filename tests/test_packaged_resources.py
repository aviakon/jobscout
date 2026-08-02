"""Files that ship with the code must survive a mounted volume over `data/`.

Production mounts a Railway volume at `/app/data`. A volume *overlays* the
directory, so anything the image shipped inside `data/` becomes invisible at
runtime. When that happened to `companies.yaml` the app built zero connectors
and every search reported "0 jobs scanned, 0 results" — silently.
"""
from app import config
from app.sources.registry import board_count, build_connectors, load_companies


def test_companies_file_is_not_inside_the_mutable_data_dir():
    assert config.COMPANIES_FILE.exists()
    assert config.DATA_DIR not in config.COMPANIES_FILE.parents


def test_sample_resume_is_packaged_too():
    assert config.SAMPLE_RESUME.exists()
    assert config.DATA_DIR not in config.SAMPLE_RESUME.parents


def test_companies_file_still_resolves_when_data_dir_is_an_empty_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # empty, as a fresh volume is
    resolved = config._companies_file()
    assert resolved.exists()
    assert resolved.parent == config.RESOURCES_DIR


def test_local_data_copy_still_wins_as_an_override(tmp_path, monkeypatch):
    override = tmp_path / "companies.yaml"
    override.write_text("greenhouse: []\n", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert config._companies_file() == override


def test_real_boards_are_configured():
    cfg = load_companies()
    assert cfg, "companies.yaml loaded empty — every search would return nothing"
    assert board_count() > 20
    # the ATS connectors, not just the key-gated aggregator
    names = {c.name for c in build_connectors()}
    assert "greenhouse" in names and "lever" in names


def test_healthz_reports_source_readiness(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["company_boards"] > 20
    assert body["companies_file_found"] is True
