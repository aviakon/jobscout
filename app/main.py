"""JobScout web app: upload a resume, run a search, review matched jobs.

Every candidate is addressed by an unguessable `public_id` token in the URL
(never the sequential DB id), and match-scoped actions are looked up through
the owning candidate — so there is no login system, but data also isn't
browsable/enumerable by a stranger with a plausible-looking URL.
"""
from __future__ import annotations

import json
import logging
import secrets

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import ads, analytics, config, db, ratelimit
from app.db import get_session, init_db
from app.models import AdInquiry, Candidate, Match
from app.pipeline import run_for_candidate
from app.resume.parser import (
    extract_text,
    extract_text_from_image,
    fetch_resume_from_url,
    is_image,
    parse_profile,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="JobScout")
BASE = config.BASE_DIR / "app"
templates = Jinja2Templates(directory=str(BASE / "templates"))
# Available to every template (the footer credit on all pages needs them)
templates.env.globals.update(
    site_author=config.SITE_AUTHOR,
    contact_email=config.CONTACT_EMAIL,
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

PROFILE_COOKIE = "jobscout_profiles"
MAX_COOKIE_PROFILES = 8
RATE_LIMIT_HTML = """<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>רגע לפני שממשיכים: JobScout</title>
<link rel="stylesheet" href="/static/style.css"></head><body>
<div class="aurora" aria-hidden="true"><span class="a1"></span><span class="a2"></span><span class="a3"></span></div>
<main class="container"><section class="card">
<h1>⏳ יותר מדי בקשות</h1>
<p class="muted">כדי לשמור על השירות זמין לכולם, יש הגבלה על מספר הסריקות בזמן קצר.
נסו שוב בעוד כמה דקות.</p>
<a href="/" class="btn-ghost">← חזרה לדף הבית</a>
</section></main></body></html>"""


@app.on_event("startup")
def _startup() -> None:
    init_db()
    from app.sources.registry import board_count

    key = config.stats_key()
    if key:
        # Printed once per boot so the owner can find their private dashboard
        # without any setup. Set STATS_KEY yourself to keep it out of the logs.
        logging.info("usage dashboard: /stats/%s", key)
    else:
        logging.warning("no stats key available (read-only data dir) - /stats is closed")

    boards = board_count()
    if boards:
        logging.info("job sources ready: %d company boards", boards)
    else:
        logging.error(
            "NO job sources configured — every search will return 0 jobs. "
            "Expected companies.yaml at %s",
            config.COMPANIES_FILE,
        )


@app.middleware("http")
async def _track_page_views(request: Request, call_next):
    """Record page views for the usage dashboard. Wrapped so analytics can
    never turn a working page into an error."""
    response = await call_next(request)
    try:
        if (request.method == "GET" and response.status_code < 400
                and analytics.should_track(request.url.path)
                and "text/html" in response.headers.get("content-type", "")):
            # automated clients are logged separately so they never inflate
            # the visitor numbers
            kind = "bot" if analytics.is_bot(request.headers.get("user-agent", "")) else "page"
            session = db.new_session()
            try:
                analytics.record(session, kind=kind, request=request)
            finally:
                session.close()
    except Exception as e:  # noqa: BLE001
        logging.warning("page-view tracking failed: %s", e)
    return response


@app.get("/healthz")
def healthz():
    """Liveness + a quick answer to 'why did the search find nothing?'."""
    from app.sources.registry import board_count

    boards = board_count()
    return {
        "ok": boards > 0,
        "company_boards": boards,
        "companies_file": str(config.COMPANIES_FILE),
        "companies_file_found": config.COMPANIES_FILE.exists(),
        "aggregator": bool(config.RAPIDAPI_KEY),
        "engine": "llm" if config.ANTHROPIC_API_KEY else "heuristic",
    }


@app.get("/advertise", response_class=HTMLResponse)
def advertise_form(request: Request, sent: int = 0):
    return templates.TemplateResponse(request, "advertise.html", {"sent": bool(sent)})


@app.post("/advertise")
def advertise_submit(
    request: Request,
    session: Session = Depends(get_session),
    company: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    message: str = Form(""),
    website: str = Form(""),  # honeypot: real people never see or fill this
):
    if website.strip():  # a bot filled the hidden field
        return RedirectResponse("/advertise?sent=1", status_code=303)
    if _rate_limited(request, "advertise", limit=5, window=3600):
        return templates.TemplateResponse(
            request, "advertise.html",
            {"error": "נשלחו יותר מדי פניות מהכתובת הזו. נסו שוב בעוד שעה."}, status_code=429)

    company, contact_name = company.strip()[:200], contact_name.strip()[:200]
    email, phone = email.strip()[:320], phone.strip()[:60]
    if not company or not (email or phone):
        return templates.TemplateResponse(
            request, "advertise.html",
            {"error": "צריך שם חברה ודרך אחת ליצור קשר: אימייל או טלפון.",
             "form": {"company": company, "contact_name": contact_name,
                      "email": email, "phone": phone, "message": message}},
            status_code=400)

    inquiry = AdInquiry(company=company, contact_name=contact_name, email=email,
                        phone=phone, message=message.strip()[:4000])
    session.add(inquiry)
    session.commit()
    analytics.record(session, kind="ad_inquiry", request=request, label=company[:120])
    _notify_new_inquiry(inquiry)
    return RedirectResponse("/advertise?sent=1", status_code=303)


def _notify_new_inquiry(inquiry) -> None:
    """Email the site owner if SMTP is set up. The inquiry is already saved, so
    a failure here costs a notification, never the lead itself."""
    if not config.email_configured():
        return
    try:
        from app.emailer import send_email

        rows = "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
            for k, v in (("חברה", inquiry.company), ("איש קשר", inquiry.contact_name),
                         ("אימייל", inquiry.email), ("טלפון", inquiry.phone),
                         ("הודעה", inquiry.message)) if v
        )
        send_email(f"פנייה חדשה לפרסום באתר: {inquiry.company}",
                   f"<h2>פנייה חדשה לפרסום</h2><table>{rows}</table>")
    except Exception as e:  # noqa: BLE001
        logging.warning("could not email the new ad inquiry: %s", e)


@app.get("/stats/{key}", response_class=HTMLResponse)
def stats_dashboard(key: str, request: Request, session: Session = Depends(get_session)):
    """Private usage dashboard.

    The site is public and has no login, so this is gated by a secret key held
    in the STATS_KEY environment variable. With no key set the route does not
    exist at all — that way an unconfigured deploy can never leak the numbers,
    and a wrong guess is indistinguishable from a missing page.
    """
    expected = config.stats_key()
    if not expected or not secrets.compare_digest(key, expected):
        raise HTTPException(404)
    inquiries = session.scalars(
        select(AdInquiry).order_by(desc(AdInquiry.created_at)).limit(50)
    ).all()
    return templates.TemplateResponse(
        request, "stats.html",
        {"s": analytics.summary(session), "key": key, "inquiries": inquiries},
    )


# --- small helpers ------------------------------------------------------------

def _get_candidate(session: Session, token: str) -> Candidate:
    candidate = session.scalar(select(Candidate).where(Candidate.public_id == token))
    if candidate is None:
        raise HTTPException(404)
    return candidate


def _get_owned_match(session: Session, candidate: Candidate, match_id: int) -> Match:
    match = session.get(Match, match_id)
    if match is None or match.candidate_id != candidate.id:
        raise HTTPException(404)
    return match


def _read_profile_tokens(request: Request) -> list[str]:
    raw = request.cookies.get(PROFILE_COOKIE, "")
    return [t for t in raw.split(",") if t][:MAX_COOKIE_PROFILES]


def _remember_profile(response, request: Request, token: str) -> None:
    """Record this candidate token in a cookie so the landing page can later
    show 'your profiles' — without ever listing anyone else's."""
    tokens = [token] + [t for t in _read_profile_tokens(request) if t != token]
    response.set_cookie(
        PROFILE_COOKIE, ",".join(tokens[:MAX_COOKIE_PROFILES]),
        max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax",
    )


def _rate_limited(request: Request, key: str, limit: int = 6, window: int = 600) -> bool:
    return ratelimit.too_many(request, key, limit, window)


# --- landing / onboarding -------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """The landing page deliberately shows no profile history: it is the first
    thing a new visitor sees, and a list of past scans belongs to them, not to
    the pitch. The tokens are still recorded in the cookie, so the list can be
    brought back without anyone losing access to their results."""
    return templates.TemplateResponse(
        request, "landing.html", {"has_key": bool(config.ANTHROPIC_API_KEY)}
    )


@app.get("/start", response_class=HTMLResponse)
def start(request: Request, candidate: str | None = None, session: Session = Depends(get_session)):
    existing = session.scalar(select(Candidate).where(Candidate.public_id == candidate)) if candidate else None
    return templates.TemplateResponse(
        request,
        "onboarding.html",
        {
            "has_key": bool(config.ANTHROPIC_API_KEY),
            "candidate": existing,
            "prefs": existing.preferences if existing else {},
        },
    )


def _build_preferences(salary_min: str, regions: str, employment_type: str,
                       remote: str, target_level: str, roles: str) -> dict:
    digits = "".join(ch for ch in (salary_min or "") if ch.isdigit())
    role_list = [r.strip() for r in (roles or "").split(",") if r.strip()][:6]
    region_list = [r.strip() for r in (regions or "").split(",") if r.strip()]
    if "all" in region_list:
        region_list = []  # "כל הארץ" => no region constraint
    # target_level arrives comma separated now that several can be chosen
    level_list = [lv.strip() for lv in (target_level or "").split(",") if lv.strip()]
    return {
        "salary_min": int(digits) if digits else None,
        "regions": region_list,
        "employment_type": employment_type or "any",
        "remote": remote or "any",
        "target_levels": level_list,
        "roles": role_list,
    }


def _onboard_error(request: Request, message: str, status_code: int = 400):
    """Re-render the onboarding page with a friendly error banner (no raw JSON)."""
    return templates.TemplateResponse(
        request,
        "onboarding.html",
        {"has_key": bool(config.ANTHROPIC_API_KEY), "candidate": None, "prefs": {}, "error": message},
        status_code=status_code,
    )


@app.post("/onboard")
async def onboard(
    request: Request,
    session: Session = Depends(get_session),
    resume_method: str = Form("file"),
    file: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
    resume_text: str = Form(""),
    resume_url: str = Form(""),
    salary_min: str = Form(""),
    regions: str = Form(""),
    employment_type: str = Form("any"),
    remote: str = Form("any"),
    target_level: str = Form(""),
    roles: str = Form(""),
    candidate_id: str = Form(""),  # actually the candidate's public token, when editing
):
    if _rate_limited(request, "onboard"):
        return _onboard_error(request, "יותר מדי סריקות בזמן קצר. נסו שוב בעוד כמה דקות.", 429)

    prefs = _build_preferences(salary_min, regions, employment_type, remote, target_level, roles)

    # Editing preferences on an existing candidate → update + re-run, no resume needed.
    token = candidate_id.strip()
    if token:
        existing = session.scalar(select(Candidate).where(Candidate.public_id == token))
        if existing is not None:
            existing.preferences_json = json.dumps(prefs, ensure_ascii=False)
            # A resume-less profile is *derived* from the roles, so changing them
            # has to rebuild it — otherwise the search keeps chasing the old role.
            # Skills added by hand are kept; they're the user's own work.
            profile = existing.profile
            if profile.get("no_resume") and prefs["roles"]:
                from app import preferences as prefs_mod

                rebuilt = prefs_mod.profile_from_preferences(prefs)
                rebuilt["skills"] = profile.get("skills", [])
                existing.profile_json = json.dumps(rebuilt, ensure_ascii=False)
            session.commit()
            _safe_scan(session, existing)
            return RedirectResponse(f"/candidate/{existing.public_id}", status_code=303)

    # No resume yet: search on the stated roles alone. Those roles are then the
    # only signal we have, so at least one is required.
    if resume_method == "none":
        from app import preferences as prefs_mod

        if not prefs["roles"]:
            return _onboard_error(
                request,
                "בלי קורות חיים צריך לפחות תפקיד אחד כדי לדעת מה לחפש. "
                "הוסיפו תפקיד בשדה התפקידים ונצא לדרך.",
            )
        candidate = Candidate(
            name="",
            resume_filename="",
            resume_text="",
            profile_json=json.dumps(prefs_mod.profile_from_preferences(prefs), ensure_ascii=False),
            preferences_json=json.dumps(prefs, ensure_ascii=False),
            skill_experience_json="{}",
        )
        session.add(candidate)
        session.commit()
        analytics.record(session, kind="onboard", request=request, label="no_resume")
        _safe_scan(session, candidate)

        resp = RedirectResponse(f"/candidate/{candidate.public_id}", status_code=303)
        _remember_profile(resp, request, candidate.public_id)
        return resp

    # Resolve resume text from the chosen intake method.
    text, fname = "", "resume.txt"
    try:
        if resume_method == "text" and resume_text.strip():
            text, fname = resume_text, "pasted.txt"
        elif resume_method == "link" and resume_url.strip():
            text, fname = fetch_resume_from_url(resume_url), "linked.txt"
        elif photo is not None and photo.filename:
            data = await photo.read()
            fname = photo.filename
            text = extract_text_from_image(fname, data)
        elif file is not None and file.filename:
            data = await file.read()
            fname = file.filename
            text = extract_text_from_image(fname, data) if is_image(fname) else extract_text(fname, data)
        elif resume_text.strip():
            text, fname = resume_text, "pasted.txt"
    except RuntimeError as e:
        return _onboard_error(request, str(e))
    except Exception as e:  # noqa: BLE001
        return _onboard_error(request, f"לא ניתן היה לקרוא את קורות החיים: {e}")

    if not text.strip():
        return _onboard_error(request, "לא הוזנו קורות חיים. העלו קובץ, הדביקו טקסט או קישור.")

    profile = parse_profile(text)
    # pre-fill the per-skill experience gauges from years inferred from the resume
    skill_years = profile.get("skill_years") or {}
    candidate = Candidate(
        name=profile.get("name", "") or fname,
        resume_filename=fname,
        resume_text=text,
        profile_json=json.dumps(profile, ensure_ascii=False),
        preferences_json=json.dumps(prefs, ensure_ascii=False),
        skill_experience_json=json.dumps(skill_years, ensure_ascii=False),
    )
    session.add(candidate)
    session.commit()
    analytics.record(session, kind="onboard", request=request, label=resume_method or "file")
    _safe_scan(session, candidate)

    resp = RedirectResponse(f"/candidate/{candidate.public_id}", status_code=303)
    _remember_profile(resp, request, candidate.public_id)
    return resp


def _safe_scan(session: Session, candidate: Candidate) -> None:
    try:
        run_for_candidate(session, candidate, location="Israel")
    except Exception as e:  # noqa: BLE001
        logging.exception("scan failed for candidate %s: %s", candidate.public_id, e)


# --- candidate dashboard -------------------------------------------------

@app.post("/candidate/{token}/search")
def search(token: str, request: Request, location: str = Form("Israel"), session: Session = Depends(get_session)):
    candidate = _get_candidate(session, token)
    if _rate_limited(request, "search"):
        return HTMLResponse(RATE_LIMIT_HTML, status_code=429)
    summary = run_for_candidate(session, candidate, location=location)
    logging.info("search summary: %s", summary)
    analytics.record(session, kind="scan", request=request, path=f"/candidate/{token}",
                     label=str(summary.get("engine", "")))
    return RedirectResponse(f"/candidate/{token}", status_code=303)


@app.get("/candidate/{token}", response_class=HTMLResponse)
def candidate_view(token: str, request: Request, session: Session = Depends(get_session)):
    candidate = _get_candidate(session, token)
    matches = session.scalars(
        select(Match)
        .where(Match.candidate_id == candidate.id, Match.status != "hidden")
        .order_by(desc(Match.score))
    ).all()
    from app import preferences as prefs_mod
    from app.resume import skills_db

    prefs = candidate.preferences
    for m in matches:
        m.fit_flags = prefs_mod.fit_flags(m.job, prefs)
        m.source_label = prefs_mod.source_label(m.job)
        m.from_company_board = prefs_mod.source_is_company_board(m.job)

    profile = candidate.profile
    ad_slots = ads.slots_for(profile)
    for ad in ad_slots:
        analytics.record(session, kind="ad_view", request=request, label=ad.slug)

    return templates.TemplateResponse(
        request,
        "candidate.html",
        {
            "candidate": candidate,
            "profile": profile,
            "matches": matches,
            "ads": ad_slots,
            "all_skills": list(skills_db.SKILLS.keys()),
            "preferences": prefs,
            # LinkedIn/Indeed coverage comes via the JSearch aggregator, which needs a key
            "has_aggregator": bool(config.RAPIDAPI_KEY),
        },
    )


@app.post("/ad/{slug}/click")
def ad_click(slug: str, request: Request, session: Session = Depends(get_session)):
    """Click beacon for the ad strip. Returns nothing: the browser follows the
    real link itself, so a slow or failed beacon never blocks the advertiser."""
    analytics.record(session, kind="ad_click", request=request, label=slug[:120])
    return Response(status_code=204)


@app.post("/candidate/{token}/match/{match_id}/status")
def set_status(token: str, match_id: int, status: str = Form(...), session: Session = Depends(get_session)):
    candidate = _get_candidate(session, token)
    match = _get_owned_match(session, candidate, match_id)
    if status not in {"new", "saved", "applied", "hidden"}:
        raise HTTPException(400, "invalid status")
    match.status = status
    session.commit()
    return {"ok": True, "status": status}


@app.post("/candidate/{token}/skills/add")
def add_skill(token: str, skill: str = Form(...), session: Session = Depends(get_session)):
    """Add a skill to the candidate's profile (from search or a custom entry)."""
    candidate = _get_candidate(session, token)
    skill = skill.strip()[:60]
    if not skill:
        raise HTTPException(400, "empty skill")
    profile = candidate.profile
    skills = profile.get("skills", [])
    if any(s.lower() == skill.lower() for s in skills):
        return {"ok": True, "skill": skill, "added": False}
    skills.insert(0, skill)
    profile["skills"] = skills
    candidate.profile_json = json.dumps(profile, ensure_ascii=False)
    session.commit()
    return {"ok": True, "skill": skill, "added": True}


@app.post("/candidate/{token}/skills/remove")
def remove_skill(token: str, skill: str = Form(...), session: Session = Depends(get_session)):
    """Remove a skill from the profile and drop any recorded experience for it."""
    candidate = _get_candidate(session, token)
    profile = candidate.profile
    profile["skills"] = [s for s in profile.get("skills", []) if s.lower() != skill.lower()]
    candidate.profile_json = json.dumps(profile, ensure_ascii=False)
    exp = candidate.skill_experience
    if skill in exp:
        exp.pop(skill, None)
        candidate.skill_experience_json = json.dumps(exp, ensure_ascii=False)
    session.commit()
    return {"ok": True, "skill": skill}


@app.post("/candidate/{token}/skill-experience")
def set_skill_experience(
    token: str,
    skill: str = Form(...),
    years: int = Form(...),
    session: Session = Depends(get_session),
):
    """Record years of experience for one skill (0 removes it)."""
    candidate = _get_candidate(session, token)
    years = max(0, min(50, years))
    exp = candidate.skill_experience
    if years == 0:
        exp.pop(skill, None)
    else:
        exp[skill] = years
    candidate.skill_experience_json = json.dumps(exp, ensure_ascii=False)
    session.commit()
    return {"ok": True, "skill": skill, "years": years}


@app.get("/candidate/{token}/match/{match_id}/cover-letter", response_class=HTMLResponse)
def cover_letter_view(token: str, match_id: int, request: Request, session: Session = Depends(get_session)):
    from app.cover_letter import generate

    candidate = _get_candidate(session, token)
    match = _get_owned_match(session, candidate, match_id)
    result = generate(candidate.profile, match.job)
    return templates.TemplateResponse(
        request,
        "cover_letter.html",
        {"match": match, "job": match.job, "candidate": candidate, "result": result},
    )


@app.get("/candidate/{token}/digest", response_class=HTMLResponse)
def digest_view(token: str, request: Request, session: Session = Depends(get_session)):
    """Read-only: show NEW matches not yet acknowledged in a digest."""
    from app.digest import DIGEST_MIN_SCORE, collect_new_matches

    candidate = _get_candidate(session, token)
    new_matches = collect_new_matches(session, candidate)
    return templates.TemplateResponse(
        request,
        "digest.html",
        {"candidate": candidate, "new_matches": new_matches, "min_score": DIGEST_MIN_SCORE},
    )


@app.post("/candidate/{token}/digest/rescan")
def digest_rescan(token: str, request: Request, location: str = Form("Israel"), session: Session = Depends(get_session)):
    """Re-fetch jobs and re-score, without acknowledging — new ones show in the digest."""
    from app.digest import run_digest

    candidate = _get_candidate(session, token)
    if _rate_limited(request, "search"):
        return HTMLResponse(RATE_LIMIT_HTML, status_code=429)
    run_digest(session, candidate, location=location, rescan=True, mark=False)
    return RedirectResponse(f"/candidate/{token}/digest", status_code=303)


@app.post("/candidate/{token}/digest/ack")
def digest_ack(token: str, session: Session = Depends(get_session)):
    """Mark all current new matches as seen (they leave the digest)."""
    from app.digest import collect_new_matches
    from app.models import utcnow

    candidate = _get_candidate(session, token)
    now = utcnow()
    for m in collect_new_matches(session, candidate):
        m.notified_at = now
    session.commit()
    return RedirectResponse(f"/candidate/{token}/digest", status_code=303)
