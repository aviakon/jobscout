"""Self-hosted usage analytics: how busy is the site, and what do people do.

No third-party tracker, no cookies for measurement, and no IP addresses stored.
A visitor is identified by sha256(daily salt + ip + user agent), truncated —
enough to count unique people per day, useless for identifying anyone, and it
rotates every midnight on its own.

Recording is strictly best-effort: analytics must never be able to break a page
or slow a request into failure, so every write is wrapped and swallowed.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import Candidate, Visit

log = logging.getLogger(__name__)

# Paths that are not page views: assets, health checks, and the dashboard itself
# (looking at your own stats should not inflate them).
_IGNORED_PREFIXES = ("/static", "/healthz", "/favicon", "/stats", "/robots.txt")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def visitor_id(request: Request) -> str:
    """Anonymous, per-day, non-reversible visitor id."""
    from app.ratelimit import client_ip

    raw = f"{config.analytics_salt()}|{_today()}|{client_ip(request)}|{request.headers.get('user-agent', '')}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:32]


def should_track(path: str) -> bool:
    return not path.startswith(_IGNORED_PREFIXES)


# Automated clients: our own deploy checks (curl), uptime probes, and crawlers.
# They are real requests, so they are still recorded — but as `bot`, never mixed
# into the human numbers, otherwise "visitors" flatters you with your own tools.
_BOT_MARKERS = (
    "bot", "crawler", "spider", "scraper", "curl", "wget", "httpx", "python-requests",
    "python-urllib", "go-http", "java/", "okhttp", "headless", "phantomjs", "puppeteer",
    "playwright", "lighthouse", "pingdom", "uptime", "monitor", "probe", "scanner",
    "preview", "facebookexternalhit", "slackbot", "whatsapp", "telegrambot", "railway",
)


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return True  # a browser always sends one; a blank UA is a script
    return any(marker in ua for marker in _BOT_MARKERS)


def record(session: Session, *, kind: str, request: Request | None = None,
           path: str = "", label: str = "") -> None:
    """Best-effort write of one event. Never raises."""
    try:
        referrer = ""
        visitor = ""
        if request is not None:
            path = path or request.url.path
            visitor = visitor_id(request)
            ref = request.headers.get("referer", "")
            # keep the origin only: no query strings, which can carry personal data
            if ref and not ref.startswith(str(request.base_url)):
                referrer = ref.split("?")[0][:300]
        session.add(Visit(day=_today(), kind=kind, path=path[:300],
                          visitor=visitor, referrer=referrer, label=label[:120]))
        session.commit()
    except Exception as e:  # noqa: BLE001 - analytics must never break a request
        log.warning("analytics record failed (%s): %s", kind, e)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass


# --- dashboard aggregates ----------------------------------------------------

def _days_back(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n - 1)).strftime("%Y-%m-%d")


def _count(session: Session, *, kind: str | None = None, since: str | None = None,
           unique: bool = False) -> int:
    col = func.count(func.distinct(Visit.visitor)) if unique else func.count(Visit.id)
    stmt = select(col)
    if kind:
        stmt = stmt.where(Visit.kind == kind)
    if since:
        stmt = stmt.where(Visit.day >= since)
    return session.scalar(stmt) or 0


def summary(session: Session) -> dict:
    """Everything the stats dashboard shows, in one pass."""
    today, week, month = _today(), _days_back(7), _days_back(30)

    def window(since: str | None) -> dict:
        return {
            "views": _count(session, kind="page", since=since),
            "visitors": _count(session, kind="page", since=since, unique=True),
            "scans": _count(session, kind="scan", since=since),
            "profiles": _count(session, kind="onboard", since=since),
            # shown separately so a busy-looking day is never just robots
            "bot_views": _count(session, kind="bot", since=since),
        }

    # daily series for the chart (30 days, zero-filled so gaps stay visible)
    rows = session.execute(
        select(Visit.day, func.count(Visit.id), func.count(func.distinct(Visit.visitor)))
        .where(Visit.kind == "page", Visit.day >= month)
        .group_by(Visit.day)
    ).all()
    by_day = {day: (views, visitors) for day, views, visitors in rows}
    series = []
    for i in range(29, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        views, visitors = by_day.get(day, (0, 0))
        series.append({"day": day, "views": views, "visitors": visitors})

    top_pages = session.execute(
        select(Visit.path, func.count(Visit.id).label("n"))
        .where(Visit.kind == "page", Visit.day >= month)
        .group_by(Visit.path).order_by(func.count(Visit.id).desc()).limit(10)
    ).all()

    referrers = session.execute(
        select(Visit.referrer, func.count(Visit.id).label("n"))
        .where(Visit.kind == "page", Visit.referrer != "", Visit.day >= month)
        .group_by(Visit.referrer).order_by(func.count(Visit.id).desc()).limit(8)
    ).all()

    # ad performance, the number an advertiser will actually ask about
    ad_rows = session.execute(
        select(Visit.label, Visit.kind, func.count(Visit.id))
        .where(Visit.kind.in_(("ad_view", "ad_click")), Visit.day >= month)
        .group_by(Visit.label, Visit.kind)
    ).all()
    ads: dict[str, dict] = {}
    for label, kind, n in ad_rows:
        slot = ads.setdefault(label, {"slug": label, "views": 0, "clicks": 0})
        slot["clicks" if kind == "ad_click" else "views"] = n
    for slot in ads.values():
        slot["ctr"] = round(100 * slot["clicks"] / slot["views"], 1) if slot["views"] else 0.0

    return {
        "today": window(today),
        "week": window(week),
        "month": window(month),
        "all_time": window(None),
        "series": series,
        "peak": max((d["views"] for d in series), default=0),
        "top_pages": [{"path": p, "n": n} for p, n in top_pages],
        "referrers": [{"src": r, "n": n} for r, n in referrers],
        "ads": sorted(ads.values(), key=lambda a: a["views"], reverse=True),
        "total_profiles": session.scalar(select(func.count(Candidate.id))) or 0,
        "first_day": session.scalar(select(func.min(Visit.day))) or "",
    }
