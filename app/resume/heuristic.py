"""Offline resume profiling — builds a structured profile without any LLM.

Used automatically when ANTHROPIC_API_KEY is not set, so JobScout works with
zero setup. Matches skills/titles/seniority from a curated vocabulary
(skills_db) against the resume text, in English and Hebrew.
"""
from __future__ import annotations

import re
from collections import Counter

from app.resume import skills_db


def _lc(text: str) -> str:
    return f" {text.lower()} "


# treat letters/digits (Latin + Hebrew) as "word" chars for boundary checks
_BOUND = r"[a-z0-9֐-׿]"
_PATTERN_CACHE: dict[str, "re.Pattern | None"] = {}

# Hebrew glues its prepositions and conjunctions straight onto the next word, so
# "machine learning" appears as "ולמידת מכונה" and "Python" as "בפייתון". A plain
# word-boundary match misses every one of those. Allowing a short prefix cluster
# is safe because a boundary is still required in front of it.
_HE_PREFIX = r"(?:[ובלמשכה]{1,2})?"
_HEBREW_CHAR = re.compile(r"[֐-׿]")


def _pattern_for(needle: str) -> "re.Pattern | None":
    needle = needle.strip().lower()
    if needle in _PATTERN_CACHE:
        return _PATTERN_CACHE[needle]
    if needle.startswith("\\"):  # author supplied an explicit regex
        try:
            pat = re.compile(needle)
        except re.error:
            pat = None
    elif _HEBREW_CHAR.match(needle):
        # Hebrew needle: allow an attached prefix ("ולמידת מכונה" -> "למידת מכונה")
        pat = re.compile(rf"(?<!{_BOUND}){_HE_PREFIX}{re.escape(needle)}(?!{_BOUND})")
    else:
        # whole-token match so "scala" != "scalable", "ui" != "building"
        pat = re.compile(rf"(?<!{_BOUND}){re.escape(needle)}(?!{_BOUND})")
    _PATTERN_CACHE[needle] = pat
    return pat


def _contains(hay: str, needle: str) -> bool:
    pat = _pattern_for(needle)
    return bool(pat and pat.search(hay))


def extract_skills(text_lc: str, limit: int = 40) -> list[str]:
    found: list[str] = []
    for canonical, aliases in skills_db.SKILLS.items():
        if any(_contains(text_lc, a) for a in aliases):
            found.append(canonical)

    # Safety net for PDFs that lost their spaces (word boundaries break, so the
    # matcher above finds almost nothing): match distinctive tech names as
    # substrings of the space-collapsed text. Only triggered when normal
    # matching is thin, to avoid false positives on well-extracted resumes.
    if len(found) < 4:
        # aliases that are substrings of common English words -> skip in lenient mode
        deny = {"scala", "react", "spark", "azure"}
        collapsed = re.sub(r"[^a-z0-9֐-׿]", "", text_lc)
        have = set(found)
        for canonical, aliases in skills_db.SKILLS.items():
            if canonical in have:
                continue
            for a in aliases:
                a = a.strip().lower()
                if a.startswith("\\") or a in deny:
                    continue
                a_c = re.sub(r"[^a-z0-9]", "", a)
                if len(a_c) >= 5 and a_c in collapsed:
                    found.append(canonical)
                    break

    counts = {
        c: sum(text_lc.count(a.strip().lower()) for a in skills_db.SKILLS[c] if not a.startswith("\\"))
        for c in found
    }
    found.sort(key=lambda c: counts.get(c, 0), reverse=True)
    return found[:limit]


# headings that introduce an explicit skills list (English + Hebrew)
_SKILL_HEADINGS = re.compile(
    r"(?im)^\s*(?:skills?|technical skills?|technologies|tech stack|tools|core competenc\w*|"
    r"כישורים|מיומנויות|טכנולוגיות|כלים|ידע טכני)\s*[:\-–]?\s*(.*)$"
)
_SKILL_SPLIT = re.compile(r"[,;•|/·•\t]+|\s{2,}|\s-\s")


def extract_listed_skills(text: str, limit: int = 40) -> list[str]:
    """Capture skills the resume lists explicitly under a Skills/כישורים heading,
    verbatim — so real skills that aren't in our vocabulary still get added."""
    out: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        m = _SKILL_HEADINGS.match(line)
        if not m:
            continue
        # the text after the heading, plus up to 2 following lines (wrapped lists)
        chunk = m.group(1) or ""
        for follow in lines[idx + 1: idx + 3]:
            if follow.strip() and not follow.strip().endswith(":"):
                chunk += " , " + follow
            else:
                break
        for tok in _SKILL_SPLIT.split(chunk):
            tok = tok.strip(" .·-–—\t").strip()
            if 1 < len(tok) <= 30 and not tok.isdigit() and tok.lower() not in seen:
                # skip obvious non-skill sentence fragments
                if len(tok.split()) <= 4:
                    seen.add(tok.lower())
                    out.append(tok)
        if len(out) >= limit:
            break
    return out[:limit]


def detect_seniority(text_lc: str) -> str:
    for level, markers in skills_db.SENIORITY_MARKERS:
        if any(_contains(text_lc, m) for m in markers):
            return level
    return "mid"


def extract_titles(text_lc: str, limit: int = 6) -> list[str]:
    hits = [t for t in skills_db.TITLE_PATTERNS if t.lower() in text_lc]
    # de-dup near-duplicates by keeping longer/more specific first
    hits.sort(key=len, reverse=True)
    out: list[str] = []
    for h in hits:
        if not any(h in o for o in out):
            out.append(h.title() if h.isascii() else h)
        if len(out) >= limit:
            break
    return out


def estimate_years(text: str) -> float:
    # 1) explicit "X years"
    years: list[int] = []
    for m in re.finditer(r"(\d{1,2})\+?\s*(?:years|yrs|שנים|שנות)", text, re.IGNORECASE):
        years.append(int(m.group(1)))
    if years:
        return float(max(years))
    # 2) infer span from 4-digit years present (earliest..latest)
    all_years = [int(y) for y in re.findall(r"(19|20)\d{2}", text)]
    all_years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    if len(all_years) >= 2:
        span = max(all_years) - min(all_years)
        if 0 < span <= 45:
            return float(span)
    return 0.0


def detect_languages(text_lc: str) -> list[str]:
    langs = [name for name, markers in skills_db.LANGUAGE_MARKERS.items()
             if any(m.strip().lower() in text_lc for m in markers)]
    # if Hebrew characters present, assume Hebrew even if not spelled out
    if "Hebrew" not in langs and re.search(r"[֐-׿]", text_lc):
        langs.append("Hebrew")
    return langs or ["English"]


def guess_name(text: str) -> str:
    # first non-empty line that looks like a name (short, no digits/@)
    for line in text.splitlines():
        line = line.strip()
        if 2 <= len(line) <= 40 and not re.search(r"[@\d/]", line) and " " in line:
            return line
    return ""


_ROLE_HINT = re.compile(r"(?i)(engineer|developer|manager|designer|analyst|architect|scientist|"
                        r"lead|consultant|specialist|administrator|devops|מפתח|מהנדס|מנהל|מעצב|אנליסט)")


def guess_headline(text: str) -> str:
    """The role line, usually right under the name (e.g. 'Full Stack Developer')."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    name = guess_name(text)
    for i, line in enumerate(lines[:6]):
        if line == name:
            continue
        if 3 <= len(line) <= 50 and "@" not in line and _ROLE_HINT.search(line):
            return line
    return ""


def build_profile(text: str) -> dict:
    text_lc = _lc(text)
    # vocabulary matches (canonical names) + every skill the resume lists verbatim
    vocab_skills = extract_skills(text_lc)
    listed = extract_listed_skills(text)
    skills: list[str] = list(vocab_skills)
    seen = {s.lower() for s in skills}
    for s in listed:
        if s.lower() not in seen:
            skills.append(s)
            seen.add(s.lower())

    titles = extract_titles(text_lc)
    headline = titles[0] if titles else (guess_headline(text) or (skills[0] + " Specialist" if skills else "Professional"))
    # make sure the headline is usable as a target title for matching
    if not titles and headline and headline not in ("Professional",):
        titles = [headline]

    # deep experience analysis: durations, per-skill years, accurate seniority
    from app.resume import experience  # local import avoids a circular dependency

    exp = experience.analyze(text, skills)
    if exp["has_dates"]:
        seniority = exp["seniority"]
        years = exp["total_years"]
    else:
        seniority = detect_seniority(text_lc)
        years = estimate_years(text)

    remote_pref = "any"
    if any(w in text_lc for w in ["remote", "עבודה מהבית", "מרחוק"]):
        remote_pref = "remote"
    elif "hybrid" in text_lc or "היברידי" in text_lc:
        remote_pref = "hybrid"

    return {
        "name": guess_name(text),
        "headline": headline if isinstance(headline, str) else str(headline),
        "seniority": seniority,
        "total_years_experience": years,
        "skills": skills,
        "skill_years": exp["skill_years"],
        "experiences": exp["experiences"],
        "education": exp["education"],
        "education_level": exp["education_summary"]["level"],
        "education_technical": exp["education_summary"]["is_technical"],
        "titles": titles,
        "industries": [],
        "languages": detect_languages(text_lc),
        "locations": ["Israel"] if re.search(r"[֐-׿]", text) or "israel" in text_lc else [],
        "remote_pref": remote_pref,
        "summary": _summary(headline, seniority, skills),
        "_engine": "heuristic",
    }


def _summary(headline, seniority: str, skills: list[str]) -> str:
    top = ", ".join(skills[:5]) if skills else "various tools"
    return f"{seniority.title()} {headline} with strengths in {top}."
