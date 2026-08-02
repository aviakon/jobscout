"""Deep resume experience analysis (offline).

Parses the work-history into dated entries and derives:
  - duration per role (from date ranges like "2019 - 2025")
  - per-skill years of experience (skills are credited the years of the roles
    that mention them) — e.g. a 2019–2025 engineer using Python => ~6y Python
  - an accurate seniority level that discounts short / military leadership
    (a few months as an army "team lead" does NOT make someone a civilian lead)

Everything is heuristic and works with no API key.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.resume import skills_db
from app.resume.heuristic import _contains, _lc

CURRENT_YEAR = datetime.now().year

_MILITARY = [
    "idf", "i.d.f", "israel defense", "unit 8200", "8200", "military", "army",
    "combat", "commander", "sergeant", "platoon", "battalion", "brigade",
    'צה"ל', "צהל", "מילואים", "שירות צבאי", "לוחם", "קצין", "מפקד", "יחידה 8200",
    "חיל", "גדוד", "מ\"כ", "מ\"פ",
]
_TECH_ROLE = [
    "engineer", "developer", "programmer", "devops", "sre", "architect", "analyst",
    "scientist", "qa", "automation", "backend", "frontend", "full stack", "fullstack",
    "software", "data ", "מפתח", "מהנדס", "תכנת", "דאטה", "אנליסט", "בודק",
]
_LEAD_ROLE = [
    "team lead", "team leader", "tech lead", "teamlead", "lead ", "leader",
    "manager", "head of", "director", "vp ", "vice president",
    "ראש צוות", "מוביל צוות", "מנהל", "cto", "chief",
]
_MANAGER_ROLE = ["manager", "head of", "director", "vp ", "מנהל", "cto", "chief", "vice president"]

# "2019 - 2025", "2019–present", "2021 to 2024", Hebrew "היום"/"כיום"
_DATE_RANGE = re.compile(
    r"(?P<s>(?:19|20)\d{2})\s*(?:[-–—]|to|עד)\s*"
    r"(?P<e>(?:19|20)\d{2}|present|current|now|today|היום|כיום|עכשיו|הווה)",
    re.IGNORECASE,
)


def _has(text_lc: str, needles: list[str]) -> bool:
    return any(n in text_lc for n in needles)


def parse_experiences(text: str) -> list[dict]:
    """Return dated work-history entries, most recent first."""
    lines = text.splitlines()
    hits = [(i, m) for i, ln in enumerate(lines) for m in [_DATE_RANGE.search(ln)] if m]
    entries: list[dict] = []
    for k, (i, m) in enumerate(hits):
        start = int(m.group("s"))
        e_raw = m.group("e").lower()
        end = int(e_raw) if e_raw.isdigit() else CURRENT_YEAR
        if end < start:
            start, end = end, start
        years = max(0.5, float(end - start))

        title = lines[i][: m.start()].strip(" -–—|,\t·•")
        if len(title) < 3 and i > 0:  # dates on their own line -> title is the line above
            title = lines[i - 1].strip(" -–—|,\t·•")

        end_body = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
        body = " ".join(lines[i + 1: end_body])
        ctx = _lc(f"{title} {body}")

        entries.append({
            "title": title[:80],
            "start": start,
            "end": end,
            "years": years,
            "body": body,
            "is_military": _has(ctx, _MILITARY),
            "is_tech": _has(ctx, _TECH_ROLE),
            "is_lead": _has(ctx, _LEAD_ROLE),
            "is_manager": _has(ctx, _MANAGER_ROLE),
        })
    entries.sort(key=lambda e: e["end"], reverse=True)
    return entries


def _career_years(entries: list[dict]) -> float:
    if not entries:
        return 0.0
    return float(max(e["end"] for e in entries) - min(e["start"] for e in entries))


def assess_seniority(entries: list[dict], text_lc: str) -> str:
    """Level from *technical* years, granting lead/manager only for sustained,
    civilian management — never for brief or military leadership (#4, #5)."""
    tech_years = sum(e["years"] for e in entries if e["is_tech"])

    civ_lead = [e for e in entries if e["is_lead"] and not e["is_military"] and e["years"] >= 1.5]
    if civ_lead:
        if any(e["is_manager"] for e in civ_lead):
            return "manager"
        return "lead"

    years = tech_years or _career_years(entries)
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    return "senior"


def skill_years(entries: list[dict], skills: list[str]) -> dict[str, int]:
    """Credit each skill the summed years of the roles that mention it (#3)."""
    cap = round(_career_years(entries)) or 0
    out: dict[str, int] = {}
    for s in skills:
        aliases = skills_db.SKILLS.get(s, [s])
        total = 0.0
        for e in entries:
            ctx = _lc(f"{e['title']} {e['body']}")
            if any(_contains(ctx, a) for a in aliases):
                total += e["years"]
        if total >= 1:
            yrs = round(total)
            out[s] = min(yrs, cap) if cap else yrs
    return out


_DEGREE_PATTERNS = [
    (r"ph\.?\s?d|doctora|דוקטור", "phd", "Ph.D"),
    (r"\bm\.?sc\b|\bm\.a\.|\bmba\b|master'?s?\b|מוסמך|תואר שני", "master", "M.Sc"),
    (r"\bb\.?sc\b|\bb\.a\.|bachelor'?s?\b|בוגר|תואר ראשון|הנדסאי", "bachelor", "B.Sc"),
    (r"\bassociate\b|תעודת|diploma", "associate", "Diploma"),
]
_FIELDS = [
    "computer science", "software engineering", "computer engineering", "electrical engineering",
    "electronics", "information systems", "data science", "mathematics", "physics", "statistics",
    "industrial engineering", "information technology", "מדעי המחשב", "הנדסת תוכנה", "הנדסת חשמל",
    "הנדסת מחשבים", "מערכות מידע", "מתמטיקה", "הנדסת תעשייה וניהול", "פיזיקה", "מדע הנתונים",
]
_INSTITUTIONS = [
    "technion", "tel aviv university", "hebrew university", "ben gurion", "bar ilan",
    "university of haifa", "weizmann", "reichman", "idc herzliya", "open university",
    "afeka", "shenkar", "sapir", "טכניון", "אוניברסיטת תל אביב", "האוניברסיטה העברית",
    "בן גוריון", "בר אילן", "אוניברסיטת חיפה", "רייכמן", "הבינתחומי", "האוניברסיטה הפתוחה", "אפקה",
]
_LEVEL_RANK_EDU = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}
_TECH_FIELDS = ("computer", "software", "electr", "data", "information", "mathematic",
                "physics", "engineering", "מחשב", "תוכנה", "חשמל", "נתונים", "מידע", "מתמטיקה", "הנדס")


def parse_education(text: str) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for line in text.splitlines():
        ll = line.lower().strip()
        if len(ll) < 4:
            continue
        level = label = None
        for pat, lvl, lab in _DEGREE_PATTERNS:
            if re.search(pat, ll):
                level, label = lvl, lab
                break
        if not level:
            continue
        field = next((f for f in _FIELDS if f in ll), "")
        inst = next((i for i in _INSTITUTIONS if i in ll), "")
        yr = re.search(r"(19|20)\d{2}", line)
        key = (level, field)
        if key in seen:
            continue
        seen.add(key)
        out.append({"level": level, "degree": label, "field": field.title() if field.isascii() else field,
                    "institution": inst.title() if inst.isascii() else inst,
                    "year": int(yr.group(0)) if yr else None})
    return out


def education_summary(entries: list[dict]) -> dict:
    if not entries:
        return {"level": "", "is_technical": False}
    top = max(entries, key=lambda e: _LEVEL_RANK_EDU.get(e["level"], 0))
    is_tech = any(any(t in (e["field"] or "").lower() for t in _TECH_FIELDS) for e in entries)
    return {"level": top["level"], "is_technical": is_tech}


def analyze(text: str, skills: list[str]) -> dict:
    """Full analysis bundle used by build_profile."""
    entries = parse_experiences(text)
    text_lc = _lc(text)
    tech_years = sum(e["years"] for e in entries if e["is_tech"])
    education = parse_education(text)
    return {
        "experiences": [
            {"title": e["title"], "start": e["start"], "end": e["end"],
             "years": e["years"], "is_military": e["is_military"]}
            for e in entries
        ],
        "seniority": assess_seniority(entries, text_lc) if entries else None,
        "total_years": round(tech_years or _career_years(entries), 1) if entries else None,
        "skill_years": skill_years(entries, skills),
        "has_dates": bool(entries),
        "education": education,
        "education_summary": education_summary(education),
    }
