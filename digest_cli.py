"""Run the daily digest for all candidates.

Re-scans every candidate, writes an HTML digest of NEW matches to data/digests/,
prints a plain-text summary, and (only if --email and SMTP env vars are set)
emails each digest.

Usage:
    python digest_cli.py                 # rescan + write HTML files
    python digest_cli.py --no-rescan     # just report new matches already stored
    python digest_cli.py --email         # also email (requires SMTP_* in .env)
    python digest_cli.py --location "Tel Aviv"
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import config
from app.db import SessionLocal, init_db
from app.digest import render_digest_html, render_digest_text, run_all_digests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("digest")


def main() -> int:
    ap = argparse.ArgumentParser(description="JobScout daily digest")
    ap.add_argument("--location", default="Israel")
    ap.add_argument("--no-rescan", action="store_true", help="don't re-fetch jobs, just report stored new matches")
    ap.add_argument("--email", action="store_true", help="email each digest (requires SMTP_* env vars)")
    ap.add_argument("--min-score", type=float, default=None)
    args = ap.parse_args()

    init_db()
    session = SessionLocal()

    kwargs = {"rescan": not args.no_rescan}
    if args.min_score is not None:
        kwargs["min_score"] = args.min_score

    digests = run_all_digests(session, location=args.location, **kwargs)
    if not digests:
        log.info("No candidates found. Add a resume first (python cli.py <resume>).")
        return 0

    total_new = 0
    for d in digests:
        c = d["candidate"]
        total_new += d["count"]
        slug = (c.name or f"candidate{c.id}").replace(" ", "_").replace("/", "_")
        out = config.DIGEST_DIR / f"digest_{c.id}_{slug}.html"
        out.write_text(render_digest_html(d), encoding="utf-8")

        print("\n" + render_digest_text(d))
        print(f"   → saved {out}")

        if args.email and d["count"] > 0:
            from app.emailer import send_email

            subject = f"JobScout: {d['count']} new job matches for {c.name or 'you'}"
            sent = send_email(subject, render_digest_html(d), render_digest_text(d))
            print("   → emailed" if sent else "   → email skipped (SMTP not configured)")

    print(f"\n=== {total_new} new matches across {len(digests)} candidate(s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
