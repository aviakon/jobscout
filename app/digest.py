"""Daily digest: re-scan a candidate and surface only NEW matches.

A match is "new" until it has been included in a digest (notified_at is set).
The first digest therefore shows all current matches; later digests show only
jobs that appeared since the previous run.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import config
from app.models import Candidate, Match, utcnow
from app.pipeline import run_for_candidate

log = logging.getLogger(__name__)

DIGEST_MIN_SCORE = 60  # only surface reasonably good new matches in the digest


def collect_new_matches(session: Session, candidate: Candidate, min_score: float = DIGEST_MIN_SCORE) -> list[Match]:
    return list(
        session.scalars(
            select(Match)
            .where(
                Match.candidate_id == candidate.id,
                Match.notified_at.is_(None),
                Match.status != "hidden",
                Match.score >= min_score,
            )
            .order_by(desc(Match.score))
        )
    )


def run_digest(
    session: Session,
    candidate: Candidate,
    location: str = "Israel",
    rescan: bool = True,
    mark: bool = True,
    min_score: float = DIGEST_MIN_SCORE,
) -> dict:
    """Re-scan (optionally), collect new matches, mark them notified."""
    scan_summary = {}
    if rescan:
        scan_summary = run_for_candidate(session, candidate, location=location)

    new_matches = collect_new_matches(session, candidate, min_score=min_score)

    if mark and new_matches:
        now = utcnow()
        for m in new_matches:
            m.notified_at = now
        session.commit()

    return {
        "candidate": candidate,
        "new_matches": new_matches,
        "count": len(new_matches),
        "generated_at": datetime.now(timezone.utc),
        "scan_summary": scan_summary,
    }


def run_all_digests(session: Session, location: str = "Israel", **kwargs) -> list[dict]:
    candidates = session.scalars(select(Candidate)).all()
    return [run_digest(session, c, location=location, **kwargs) for c in candidates]


# --- standalone HTML rendering (for saving to file or emailing) ---------------

def render_digest_html(digest: dict) -> str:
    c: Candidate = digest["candidate"]
    name = html.escape(c.name or c.resume_filename or f"Candidate #{c.id}")
    when = digest["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for m in digest["new_matches"]:
        j = m.job
        why = "".join(f"<li>✅ {html.escape(w)}</li>" for w in m.why)
        gaps = "".join(f"<li>⚠️ {html.escape(g)}</li>" for g in m.gaps)
        rows.append(f"""
        <div style="border:1px solid #2c3358;border-radius:10px;padding:14px;margin:10px 0;background:#232a4a;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <a href="{html.escape(j.url)}" style="color:#8fb0ff;font-size:17px;font-weight:600;text-decoration:none;">
              {html.escape(j.title)}</a>
            <span style="background:#4cc9a0;color:#0b0e18;border-radius:8px;padding:2px 10px;font-weight:700;">
              {int(m.score)}</span>
          </div>
          <div style="color:#9aa3c0;font-size:14px;margin:4px 0;">
            {html.escape(j.company)} · {html.escape(j.location or '')} · {html.escape(j.source)}</div>
          <ul style="margin:6px 0;padding-inline-start:18px;font-size:14px;">{why}{gaps}</ul>
        </div>""")

    body = "".join(rows) or "<p style='color:#9aa3c0;'>No new matches since the last digest. 🎉</p>"
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>JobScout Digest: {name}</title></head>
<body style="font-family:Assistant,Segoe UI,Arial,sans-serif;background:#0f1220;color:#e8ebf5;max-width:720px;margin:0 auto;padding:24px;">
  <h1 style="font-size:22px;">🧭 JobScout: משרות חדשות עבור {name}</h1>
  <p style="color:#9aa3c0;">{digest['count']} התאמות חדשות · נוצר בתאריך {when}</p>
  {body}
  <p style="color:#6b7394;font-size:12px;margin-top:24px;">נשלח ע\"י JobScout · לא לחיצה על קישורים שאינך מכיר.</p>
</body></html>"""


def render_digest_text(digest: dict) -> str:
    """Plain-text digest for terminals / plain email."""
    c: Candidate = digest["candidate"]
    lines = [f"JobScout digest for {c.name or c.id}: {digest['count']} new matches", "=" * 50]
    for m in digest["new_matches"]:
        j = m.job
        lines.append(f"[{int(m.score):>3}] {j.title} at {j.company} ({j.source})")
        if m.why:
            lines.append(f"       {m.why[0]}")
        if j.url:
            lines.append(f"       {j.url}")
    if not digest["new_matches"]:
        lines.append("No new matches since the last digest.")
    return "\n".join(lines)
