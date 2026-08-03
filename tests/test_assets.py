"""Static assets must not be served stale after a deploy.

Without a fingerprint in the URL, a returning visitor keeps the CSS and JS
their browser cached before the deploy — so a fix stays invisible to exactly
the people who already use the site, and a new control looks broken because
its script never arrived.
"""
import re


def test_pages_request_a_versioned_stylesheet_and_script(client):
    html = client.get("/").text
    assert re.search(r'/static/style\.css\?v=\d+', html), "stylesheet is not cache busted"
    assert re.search(r'/static/app\.js\?v=\d+', html), "script is not cache busted"


def test_every_page_uses_the_same_version(client):
    def version(url):
        m = re.search(r'/static/app\.js\?v=(\d+)', client.get(url).text)
        return m.group(1) if m else None

    versions = {version(u) for u in ("/", "/start", "/advertise")}
    assert len(versions) == 1 and None not in versions, versions


def test_the_version_tracks_the_files(monkeypatch, tmp_path):
    """A new deploy of changed assets must produce a new URL."""
    import app.main as main_module

    css, js = tmp_path / "style.css", tmp_path / "app.js"
    css.write_text("a{}", encoding="utf-8")
    js.write_text("//", encoding="utf-8")
    monkeypatch.setattr(main_module, "BASE", tmp_path.parent)
    monkeypatch.setattr(main_module, "BASE", tmp_path)  # static/ lives under BASE

    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "style.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "static" / "app.js").write_text("//", encoding="utf-8")

    import os

    first = main_module._asset_version()
    os.utime(tmp_path / "static" / "app.js", (2_000_000_000, 2_000_000_000))
    assert main_module._asset_version() != first


def test_the_version_survives_missing_files(monkeypatch, tmp_path):
    """A fingerprint is a nicety; failing to compute one must not break pages."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "BASE", tmp_path / "does-not-exist")
    assert main_module._asset_version() == "0"
