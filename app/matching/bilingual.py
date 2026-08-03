"""English <-> Hebrew term expansion, so a profile written in one language can
still match a posting written in the other.

Israeli job ads mix languages freely: the same role is "AI Engineer" on one
board and "מהנדס בינה מלאכותית" on another. Without this, an English resume
simply never sees the Hebrew ad, and vice versa — not because the match is
poor, but because no word overlapped.

The glossary is intentionally phrase-level rather than word-level. Translating
word by word produces nonsense ("data" -> "נתונים" is fine, but "data science"
is "מדעי הנתונים", not two separate words), and job titles are exactly where
that goes wrong.
"""
from __future__ import annotations

# English phrase -> Hebrew surface forms seen in real Israeli postings.
# Lowercased on both sides; matching is boundary aware, so short entries like
# "ai" are safe (they will not fire inside "email" or "training").
GLOSSARY: dict[str, list[str]] = {
    # --- AI / data ---------------------------------------------------------
    "ai": ["בינה מלאכותית"],
    "artificial intelligence": ["בינה מלאכותית"],
    "machine learning": ["למידת מכונה", "לימוד מכונה", "למידת מכונה"],
    "deep learning": ["למידה עמוקה"],
    "data science": ["מדעי הנתונים", "מדע הנתונים"],
    "data scientist": ["מדען נתונים", "מדענית נתונים"],
    "data analyst": ["אנליסט נתונים", "מנתח נתונים", "אנליסט"],
    "data engineer": ["מהנדס נתונים", "מהנדסת נתונים"],
    "algorithms": ["אלגוריתמים", "אלגוריתמיקה"],
    "algorithm engineer": ["מהנדס אלגוריתמים"],
    "computer vision": ["ראייה ממוחשבת", "ראיה ממוחשבת"],
    "nlp": ["עיבוד שפה טבעית"],
    "big data": ["ביג דאטה"],
    "analytics": ["אנליטיקה"],
    # --- engineering roles -------------------------------------------------
    "software engineer": ["מהנדס תוכנה", "מהנדסת תוכנה"],
    "software developer": ["מפתח תוכנה", "מפתחת תוכנה"],
    "developer": ["מפתח", "מפתחת"],
    "engineer": ["מהנדס", "מהנדסת"],
    "backend": ["בק אנד", "צד שרת", "באקאנד"],
    "frontend": ["פרונט אנד", "צד לקוח", "פרונטאנד"],
    "full stack": ["פול סטאק", "פולסטאק"],
    "mobile": ["מובייל", "אפליקציות"],
    "android": ["אנדרואיד"],
    "ios": ["אייפון"],
    "embedded": ["מערכות משובצות", "אמבדד"],
    "firmware": ["קושחה"],
    "devops": ["דבאופס"],
    "infrastructure": ["תשתיות"],
    "cloud": ["ענן"],
    "automation": ["אוטומציה"],
    "qa": ["בדיקות תוכנה", "בודק תוכנה", "בדיקות"],
    "testing": ["בדיקות"],
    "security": ["אבטחת מידע", "סייבר"],
    "cyber": ["סייבר"],
    "architect": ["ארכיטקט"],
    "system": ["מערכות"],
    "network": ["תקשורת", "רשתות"],
    "database": ["מסדי נתונים", "בסיסי נתונים"],
    # --- seniority / structure --------------------------------------------
    "senior": ["בכיר", "בכירה"],
    "junior": ["ג'וניור", "זוטר"],
    "team lead": ["ראש צוות", "ראשת צוות"],
    "tech lead": ["ראש צוות טכנולוגי"],
    "manager": ["מנהל", "מנהלת"],
    "student": ["סטודנט", "סטודנטית"],
    "part time": ["משרה חלקית"],
    "full time": ["משרה מלאה"],
    "hybrid": ["היברידי", "היברידית"],
    "remote": ["עבודה מהבית", "מרחוק"],
    # --- product / design / other ------------------------------------------
    "product manager": ["מנהל מוצר", "מנהלת מוצר"],
    "project manager": ["מנהל פרויקטים", "מנהלת פרויקטים"],
    "designer": ["מעצב", "מעצבת"],
    "ux": ["חווית משתמש", "חוויית משתמש"],
    "support": ["תמיכה"],
    "sales": ["מכירות"],
    "marketing": ["שיווק"],
    "finance": ["כספים"],
    "recruiter": ["מגייס", "מגייסת", "גיוס"],
}

# Hebrew -> English, derived from the same table so the two can never drift.
_REVERSE: dict[str, list[str]] = {}
for _en, _hes in GLOSSARY.items():
    for _he in _hes:
        _REVERSE.setdefault(_he, []).append(_en)


def counterparts(term: str) -> list[str]:
    """Every known other-language form of one term, in either direction."""
    key = (term or "").strip().lower()
    if not key:
        return []
    return list(dict.fromkeys(GLOSSARY.get(key, []) + _REVERSE.get(key, [])))


def expand(phrase: str) -> list[str]:
    """Other-language forms of a phrase, matching whole entries first and then
    any glossary phrase contained in it.

    "Senior AI Engineer" yields the Hebrew for senior, for ai and for engineer,
    so it overlaps "מהנדס בינה מלאכותית בכיר" even though neither string was
    ever translated as a whole.
    """
    text = (phrase or "").strip().lower()
    if not text:
        return []

    out: list[str] = list(counterparts(text))
    padded = f" {text} "
    for key in GLOSSARY:
        if f" {key} " in padded and key != text:
            out.extend(GLOSSARY[key])
    for key in _REVERSE:
        if f" {key} " in padded and key != text:
            out.extend(_REVERSE[key])
    return list(dict.fromkeys(out))


def expand_all(phrases: list[str]) -> list[str]:
    """Bilingual counterparts for a list of phrases, de-duplicated."""
    out: list[str] = []
    for p in phrases:
        out.extend(expand(p))
    return list(dict.fromkeys(out))
