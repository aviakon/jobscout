"""Command-line runner: parse a resume file and run the full pipeline.

Usage:
    python cli.py path/to/resume.pdf [--location Israel]
"""
from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal, init_db
from app.models import Candidate
from app.pipeline import run_for_candidate
from app.resume.parser import extract_text, parse_profile


def main() -> int:
    ap = argparse.ArgumentParser(description="JobScout CLI")
    ap.add_argument("resume", help="Path to resume file (.pdf/.docx/.txt)")
    ap.add_argument("--location", default="Israel")
    args = ap.parse_args()

    init_db()
    with open(args.resume, "rb") as f:
        data = f.read()

    text = extract_text(args.resume, data)
    print(f"Extracted {len(text)} chars from resume.")
    profile = parse_profile(text)
    print("Profile:", json.dumps(profile, ensure_ascii=False, indent=2))

    session = SessionLocal()
    candidate = Candidate(
        name=profile.get("name", ""),
        resume_filename=args.resume,
        resume_text=text,
        profile_json=json.dumps(profile, ensure_ascii=False),
    )
    session.add(candidate)
    session.commit()

    summary = run_for_candidate(session, candidate, location=args.location)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nOpen the web app and visit /candidate/{candidate.id} to review matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
