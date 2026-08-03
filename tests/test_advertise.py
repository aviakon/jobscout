"""The advertise form: the site's only lead-capture path.

A lost submission is a lost customer, so the rules here are strict: a valid
submission must be stored even if notification fails, an invalid one must come
back with the typed values intact, and the collected contact details must never
be readable without the dashboard key.
"""
import pytest
from sqlalchemy import select

from app import config
from app.models import AdInquiry


def _ip(n):
    return {"X-Forwarded-For": f"198.51.100.{n}"}


def test_the_form_is_publicly_reachable(client):
    resp = client.get("/advertise")
    assert resp.status_code == 200
    assert 'name="company"' in resp.text


def test_a_submission_is_stored(client, sqlite_session):
    resp = client.post("/advertise", data={
        "company": "Acme", "contact_name": "דנה לוי",
        "email": "dana@acme.com", "phone": "050-1234567",
        "message": "מגייסים מפתחי Backend",
    }, headers=_ip(1), follow_redirects=False)
    assert resp.status_code == 303

    inquiry = sqlite_session.scalar(select(AdInquiry))
    assert inquiry.company == "Acme"
    assert inquiry.contact_name == "דנה לוי"
    assert inquiry.email == "dana@acme.com"
    assert inquiry.phone == "050-1234567"
    assert "Backend" in inquiry.message


def test_the_sender_gets_a_confirmation(client):
    resp = client.post("/advertise", data={"company": "Acme", "email": "a@b.com"},
                       headers=_ip(2), follow_redirects=True)
    assert "הפנייה נשלחה" in resp.text


def test_a_company_name_alone_is_not_enough(client, sqlite_session):
    """Without a way to reply, the lead is worthless."""
    resp = client.post("/advertise", data={"company": "Acme"}, headers=_ip(3))
    assert resp.status_code == 400
    assert sqlite_session.scalar(select(AdInquiry)) is None


def test_contact_details_alone_are_not_enough(client, sqlite_session):
    resp = client.post("/advertise", data={"email": "a@b.com"}, headers=_ip(4))
    assert resp.status_code == 400
    assert sqlite_session.scalar(select(AdInquiry)) is None


def test_either_email_or_phone_is_accepted(client, sqlite_session):
    client.post("/advertise", data={"company": "OnlyPhone", "phone": "050-7654321"},
                headers=_ip(5), follow_redirects=False)
    assert sqlite_session.scalar(select(AdInquiry)).company == "OnlyPhone"


def test_a_rejected_form_keeps_what_was_typed(client):
    resp = client.post("/advertise", data={"company": "", "contact_name": "דנה",
                                           "message": "טקסט ארוך שלא נרצה להקליד שוב"},
                       headers=_ip(6))
    assert "דנה" in resp.text
    assert "טקסט ארוך שלא נרצה להקליד שוב" in resp.text


def test_the_honeypot_swallows_bots(client, sqlite_session):
    """Hidden field filled in means a script, not a person. It is accepted
    silently so the bot does not learn to retry."""
    resp = client.post("/advertise", data={"company": "SpamCo", "email": "spam@x.com",
                                           "website": "http://spam.example"},
                       headers=_ip(7), follow_redirects=False)
    assert resp.status_code == 303
    assert sqlite_session.scalar(select(AdInquiry)) is None


def test_submissions_are_rate_limited(client):
    codes = [client.post("/advertise", data={"company": f"Co{i}", "email": "a@b.com"},
                         headers=_ip(8), follow_redirects=False).status_code
             for i in range(8)]
    assert 303 in codes
    assert 429 in codes


def test_a_failing_notification_does_not_lose_the_lead(client, sqlite_session, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(config, "email_configured", lambda: True)
    monkeypatch.setattr("app.emailer.send_email",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))

    resp = client.post("/advertise", data={"company": "Acme", "email": "a@b.com"},
                       headers=_ip(9), follow_redirects=False)
    assert resp.status_code == 303
    assert sqlite_session.scalar(select(AdInquiry)) is not None


# --- privacy -----------------------------------------------------------------

def test_inquiries_are_not_readable_without_the_dashboard_key(client, sqlite_session, monkeypatch):
    client.post("/advertise", data={"company": "PrivateCo", "email": "secret@co.com"},
                headers=_ip(10), follow_redirects=False)

    monkeypatch.setattr(config, "stats_key", lambda: "the-key")
    assert client.get("/stats/wrong-key").status_code == 404

    public = client.get("/").text + client.get("/advertise").text
    assert "secret@co.com" not in public
    assert "PrivateCo" not in public


def test_the_dashboard_shows_them_to_the_owner(client, sqlite_session, monkeypatch):
    client.post("/advertise", data={"company": "PrivateCo", "email": "secret@co.com",
                                    "message": "רוצים לפרסם"},
                headers=_ip(11), follow_redirects=False)

    monkeypatch.setattr(config, "stats_key", lambda: "the-key")
    page = client.get("/stats/the-key").text
    assert "PrivateCo" in page
    assert "secret@co.com" in page
    assert "רוצים לפרסם" in page
