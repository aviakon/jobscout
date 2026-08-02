"""JobScout web app: upload a resume, run a search, review matched jobs.

Every candidate is addressed by an unguessable `public_id` token in the URL
(never the sequential DB id), and match-scoped actions are looked up through
the owning candidate — so there is no login system, but data also isn't
browsable/enumerable by a stranger with a plausible-looking URL.
"""
from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import config, ratelimit
from app.db import get_session, init_db
from app.models import Candidate, Match
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
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

PROFILE_COOKIE = "jobscout_profiles"
MAX_COOKIE_PROFILES = 8
RATE_LIMIT_HTML = """<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>רגע לפני שממשיכים — JobScout</title>
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
def home(request: Request, session: Session = Depends(get_session)):
    tokens = _read_profile_tokens(request)
    candidates = []
    if tokens:
        rows = session.scalars(select(Candidate).where(Candidate.public_id.in_(tokens))).all()
        by_token = {c.public_id: c for c in rows}
        candidates = [by_token[t] for t in tokens if t in by_token]  # most-recent first
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"candidates": candidates, "has_key": bool(config.ANTHROPIC_API_KEY)},
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
    return {
        "salary_min": int(digits) if digits else None,
        "regions": region_list,
        "employment_type": employment_type or "any",
        "remote": remote or "any",
        "target_level": target_level or "",
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
            session.commit()
            _safe_scan(session, existing)
            return RedirectResponse(f"/candidate/{existing.public_id}", status_code=303)

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

    return templates.TemplateResponse(
        request,
        "candidate.html",
        {
            "candidate": candidate,
            "profile": candidate.profile,
            "matches": matches,
            "all_skills": list(skills_db.SKILLS.keys()),
            "preferences": prefs,
        },
    )


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
