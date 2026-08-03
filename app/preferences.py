"""Apply candidate search preferences to the pipeline and compute fit badges.

Preferences shape (stored on Candidate.preferences_json):
    { salary_min, region, employment_type, remote, target_level, roles[] }
"""
from __future__ import annotations

# region -> location keywords (Hebrew + English, lowercased)
REGION_CITIES: dict[str, list[str]] = {
    "center": [
        "tel aviv", "tel-aviv", "תל אביב", "ramat gan", "רמת גן", "givatayim", "גבעתיים",
        "herzliya", "הרצליה", "petah tikva", "petach tikva", "פתח תקווה", "holon", "חולון",
        "bat yam", "בת ים", "bnei brak", "בני ברק", "rishon", "ראשון לציון", "or yehuda",
        "אור יהודה", "ramat hasharon", "רמת השרון", "rosh haayin", "ראש העין", "kiryat ono", "קרית אונו",
    ],
    "sharon": ["netanya", "נתניה", "kfar saba", "כפר סבא", "raanana", "רעננה", "hod hasharon", "הוד השרון"],
    "north": ["haifa", "חיפה", "nazareth", "נצרת", "carmiel", "כרמיאל", "afula", "עפולה",
              "nahariya", "נהריה", "akko", "עכו", "tiberias", "טבריה", "yokneam", "יקנעם"],
    "south": ["beer sheva", "be'er sheva", "באר שבע", "ashdod", "אשדוד", "ashkelon", "אשקלון",
              "eilat", "אילת", "dimona", "דימונה", "netivot", "נתיבות", "kiryat gat", "קרית גת"],
    "jerusalem": ["jerusalem", "ירושלים", "beit shemesh", "בית שמש", "maale adumim", "מעלה אדומים"],
}

_LEVEL_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "manager": 5, "director": 6}


def get_regions(prefs: dict) -> list[str]:
    """Selected work regions as a list. Empty / 'all' means no constraint.

    Accepts both the new `regions` list and the legacy `region` string.
    """
    regs = prefs.get("regions")
    if regs is None:
        one = prefs.get("region")
        regs = [one] if one else []
    return [r for r in regs if r and r not in ("all", "remote")]


def region_matches(location: str | None, region: str) -> bool | None:
    """True = in region, False = clearly a different region, None = unknown/remote."""
    if not region or region in ("all", "remote"):
        return None
    loc = (location or "").lower()
    if not loc:
        return None
    if any(k in loc for k in REGION_CITIES.get(region, [])):
        return True
    for other, kws in REGION_CITIES.items():
        if other != region and any(k in loc for k in kws):
            return False
    return None


def region_fit(location: str | None, prefs: dict) -> bool | None:
    """Fit against ANY of the selected regions. True/False/None (unknown)."""
    regs = get_regions(prefs)
    if not regs:
        return None
    results = [region_matches(location, r) for r in regs]
    if any(x is True for x in results):
        return True
    if any(x is None for x in results):
        return None
    return False


def remote_matches(job_remote, pref: str) -> bool | None:
    if not pref or pref == "any":
        return None
    val = str(job_remote or "").lower()
    if pref == "remote":
        return True if ("remote" in val or "מהבית" in val or val in ("true", "1")) else None
    if pref == "hybrid":
        return True if "hybrid" in val or "היברידי" in val else None
    return None


def level_matches(job_seniority: str, target_level: str) -> bool | None:
    if not target_level:
        return None
    a, b = _LEVEL_RANK.get(job_seniority), _LEVEL_RANK.get(target_level)
    if a is None or b is None:
        return None
    return abs(a - b) <= 1


def fit_flags(job, prefs: dict) -> list[str]:
    """Positive, human-readable fit badges for a job card (Hebrew)."""
    flags: list[str] = []
    if region_fit(getattr(job, "location", ""), prefs) is True:
        flags.append("✓ באזור שלך")
    if remote_matches(getattr(job, "remote", None), prefs.get("remote", "any")) is True:
        flags.append("✓ מתאים לעבודה מהבית")
    return flags


def preference_boost(job, prefs: dict) -> float:
    """Soft ranking bonus (0..~0.13) for jobs matching region / remote preference.

    Region is a *preference*, never a hard filter — out-of-region jobs still
    appear, just ranked lower, so a search never comes back empty.
    """
    boost = 0.0
    if region_fit(getattr(job, "location", ""), prefs) is True:
        boost += 0.08
    if remote_matches(getattr(job, "remote", None), prefs.get("remote", "any")) is True:
        boost += 0.05
    return boost


# Friendly Hebrew names for where a posting came from, shown on match cards.
_SOURCE_LABELS = {
    "greenhouse": "לוח החברה (Greenhouse)",
    "lever": "לוח החברה (Lever)",
    "ashby": "לוח החברה (Ashby)",
    "comeet": "לוח החברה (Comeet)",
    "smartrecruiters": "לוח החברה (SmartRecruiters)",
    "jsearch": "אגרגטור משרות",
}


def source_label(job) -> str:
    """Human-readable origin. For aggregated results this is the site the posting
    actually came from (LinkedIn, Indeed, ...) rather than the aggregator itself."""
    detail = (getattr(job, "source_detail", "") or "").strip()
    source = (getattr(job, "source", "") or "").strip()
    if detail:
        return detail
    return _SOURCE_LABELS.get(source, source or "לא ידוע")


def source_is_company_board(job) -> bool:
    return (getattr(job, "source", "") or "") in {
        "greenhouse", "lever", "ashby", "comeet", "smartrecruiters"
    }


_ISRAEL_HINTS = ["israel", "ישראל"]
_REMOTE_HINTS = ["remote", "anywhere", "work from home", "wfh", "מהבית", "מרחוק", "עבודה מהבית", "distributed"]
# extra Israeli places beyond the region map
_ISRAEL_CITIES = [
    "modiin", "modi'in", "rehovot", "ness ziona", "nes ziona", "yavne", "caesarea",
    "yokneam", "airport city", "gush dan", "sharon", "raanana", "ra'anana", "kfar",
    "מודיעין", "רחובות", "נס ציונה", "יבנה", "קיסריה", "גוש דן",
]


def _loc(job) -> str:
    return (getattr(job, "location", "") or "").lower()


def is_remote(job) -> bool:
    txt = f"{_loc(job)} {getattr(job, 'remote', '') or ''}".lower()
    return any(h in txt for h in _REMOTE_HINTS)


def is_in_israel(job) -> bool:
    loc = _loc(job)
    if any(h in loc for h in _ISRAEL_HINTS) or any(c in loc for c in _ISRAEL_CITIES):
        return True
    for kws in REGION_CITIES.values():  # any known Israeli city
        if any(k in loc for k in kws):
            return True
    return False


_FOREIGN_HINTS = [
    "usa", "united states", "u.s.", "america", "san francisco", "new york", "boston",
    "austin", "seattle", "california", "chicago", "denver", "atlanta", "canada", "toronto",
    "vancouver", "uk", "united kingdom", "london", "manchester", "ireland", "dublin",
    "europe", "eu ", "emea", "germany", "berlin", "munich", "france", "paris", "spain",
    "madrid", "barcelona", "portugal", "lisbon", "netherlands", "amsterdam", "poland",
    "warsaw", "krakow", "romania", "bucharest", "bulgaria", "sofia", "hungary", "budapest",
    "czech", "prague", "ukraine", "kyiv", "italy", "rome", "milan", "sweden", "stockholm",
    "denmark", "norway", "finland", "switzerland", "zurich", "belgium", "brussels",
    "greece", "athens", "cyprus", "india", "bangalore", "bengaluru", "hyderabad", "pune",
    "singapore", "japan", "tokyo", "china", "shanghai", "beijing", "hong kong", "korea",
    "seoul", "australia", "sydney", "melbourne", "brazil", "mexico", "argentina", "chile",
    "philippines", "manila", "vietnam", "turkey", "istanbul", "dubai", "uae", "egypt",
    "south africa", "nigeria", "kenya",
]


def _has_foreign_geo(job) -> bool:
    txt = f"{_loc(job)} {getattr(job, 'remote', '') or ''}".lower()
    return any(f in txt for f in _FOREIGN_HINTS)


def allowed_location(job) -> bool:
    """Keep only jobs in Israel, or truly location-agnostic remote jobs (#1).

    - Israeli location -> keep.
    - Any explicit foreign geo (even 'Remote - Japan') -> drop; a foreign-pinned
      role isn't realistic for an Israel-based candidate.
    - Generic remote with no foreign geo, or a blank location -> keep."""
    if is_in_israel(job):
        return True
    if _has_foreign_geo(job):
        return False
    if is_remote(job):
        return True
    return not _loc(job).strip()


_LEVEL_ORDER = ["intern", "junior", "mid", "senior", "lead", "manager", "director"]


def level_mismatch(job_seniority: str, candidate_level: str, target_level: str = "") -> bool:
    """True if the job's level is unrealistic for the candidate — too senior
    (a team-lead role for a mid, #4/#5) or far too junior. Respects an explicit
    target level as the reference point."""
    ref = target_level or candidate_level
    try:
        cand = _LEVEL_ORDER.index(ref)
        job = _LEVEL_ORDER.index(job_seniority)
    except ValueError:
        return False
    return abs(job - cand) >= 2


def profile_from_preferences(prefs: dict) -> dict:
    """Build a search profile for someone who has no resume yet.

    The roles they typed are the only signal we have, so they stand in for the
    resume's titles and headline — enough for the prefilter, the role-family
    filter and the seniority filter to do real work. Skills stay empty on
    purpose: we don't invent a stack the person never claimed. They can add
    skills by hand on the profile page, and each one sharpens the next search.
    """
    from app import config

    roles = [r for r in prefs.get("roles", []) if r][:6]
    headline = roles[0] if roles else ""
    listed = ", ".join(roles)
    return {
        "name": "",
        "headline": headline,
        "seniority": prefs.get("target_level") or "mid",
        "total_years_experience": 0,
        "skills": [],
        "skill_years": {},
        "experiences": [],
        "education": [],
        "titles": roles,
        "industries": [],
        "languages": [],
        "locations": ["Israel"],
        "remote_pref": prefs.get("remote", "any") or "any",
        "summary": f"פרופיל לפי העדפות בלבד: {listed}. הוסיפו כישורים כדי לשפר את ההתאמות."
                   if listed else "",
        # describes the *scoring* engine, same as a parsed resume would
        "_engine": "llm" if config.ANTHROPIC_API_KEY else "heuristic",
        "no_resume": True,
    }


def augment_queries(queries: list[str], prefs: dict) -> list[str]:
    roles = [r for r in prefs.get("roles", []) if r]
    out = list(queries)
    for r in roles:
        if r not in out:
            out.append(r)
    return out
