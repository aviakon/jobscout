"""Role-family classification and alignment.

Classifies both a job (from its title) and a candidate (from titles/headline/
skills) into role families, so we can stop offering off-field roles — e.g. a
"Technical Account Manager" or "Recruiter" to a backend engineer.
"""
from __future__ import annotations

from app.resume.heuristic import _contains, _lc

# family -> title/keyword signatures (word-boundary matched)
FAMILY_SIGNS: dict[str, list[str]] = {
    "backend": ["backend", "back end", "back-end", "server side", "server-side", "מפתח שרת", "צד שרת", "בק אנד", "באקאנד"],
    "frontend": ["frontend", "front end", "front-end", "web developer", "ui developer", "react developer", "פרונט אנד", "צד לקוח", "פרונטאנד"],
    "fullstack": ["full stack", "fullstack", "full-stack", "פול סטאק", "פולסטאק"],
    "mobile": ["mobile", "ios developer", "android developer", "react native", "flutter", "מובייל", "אנדרואיד", "פיתוח אפליקציות"],
    "data": ["data engineer", "data analyst", "data scientist", "analytics engineer", "bi developer",
             "big data", "data platform", "business intelligence", "מדען נתונים", "מדענית נתונים", "מהנדס נתונים", "אנליסט נתונים", "מנתח נתונים", "מדעי הנתונים"],
    "ml": ["machine learning", "ml engineer", "ai engineer", "ai", "deep learning", "nlp engineer",
           "computer vision", "algorithm engineer", "algorithms", "research engineer", "applied scientist", "בינה מלאכותית", "למידת מכונה", "למידה עמוקה", "אלגוריתמים", "אלגוריתמיקה", "ראייה ממוחשבת"],
    "devops": ["devops", "sre", "site reliability", "infrastructure engineer", "platform engineer",
               "cloud engineer", "production engineer", "systems engineer", "דבאופס", "תשתיות"],
    "qa": ["qa engineer", "quality assurance", "test automation", "automation engineer", "sdet", "qa lead", "בדיקות תוכנה"],
    "security": ["security engineer", "cyber", "infosec", "appsec", "penetration", "security researcher", "סייבר", "אבטחת מידע"],
    "embedded": ["embedded", "firmware", "fpga", "rtos", "hardware engineer", "מערכות משובצות", "אמבדד", "קושחה"],
    "software": ["software engineer", "software developer", "software architect", "programmer",
                 "מפתח", "מהנדס תוכנה", "developer"],
    "product": ["product manager", "product owner", "group product", "מנהל מוצר", "מנהלת מוצר"],
    "design": ["ux designer", "ui designer", "product designer", "ux/ui", "graphic designer", "מעצב", "מעצבת", "חווית משתמש", "חוויית משתמש"],
    "management": ["engineering manager", "team lead", "team leader", "tech lead", "r&d manager",
                   "vp engineering", "vp r&d", "group manager", "director of engineering", "cto", "head of engineering", "ראש צוות", "ראשת צוות", "מנהל פיתוח"],
    "sales": ["sales", "account executive", "business development", "sdr", "bdr", "sales development", "מכירות"],
    "success": ["customer success", "account manager", "technical account", "support engineer",
                "solutions engineer", "solution architect", "solutions architect", "implementation",
                "professional services", "delivery manager", "customer support", "תמיכה טכנית"],
    "marketing": ["marketing", "seo specialist", "growth", "content writer", "social media", "demand generation", "שיווק"],
    "finance": ["finance", "accountant", "controller", "fp&a", "bookkeeper", "כספים", "חשב", "הנהלת חשבונות"],
    "hr": ["recruiter", "talent acquisition", "people operations", "hr business", "hrbp", "sourcer", "גיוס", "מגייס", "מגייסת", "משאבי אנוש"],
    "operations": ["operations manager", "logistics", "office manager", "procurement"],
}

ENGINEERING = {"backend", "frontend", "fullstack", "mobile", "data", "ml", "devops",
               "qa", "security", "embedded", "software"}

# families that read as "close enough" to each other
_ADJ: dict[str, set[str]] = {
    "backend": {"fullstack", "devops", "data", "ml", "software"},
    "frontend": {"fullstack", "mobile", "software", "design"},
    "fullstack": {"backend", "frontend", "software"},
    "mobile": {"frontend", "fullstack", "software"},
    "data": {"backend", "ml", "software"},
    "ml": {"data", "backend", "software"},
    "devops": {"backend", "security", "software"},
    "qa": {"software", "backend", "frontend"},
    "security": {"devops", "backend", "software"},
    "embedded": {"software"},
    "software": ENGINEERING,
}

# skills that hint a candidate's family (when the title is generic)
_SKILL_FAMILY: dict[str, str] = {
    "React": "frontend", "Angular": "frontend", "Vue": "frontend", "HTML/CSS": "frontend",
    "iOS": "mobile", "Android": "mobile", "React Native": "mobile", "Flutter": "mobile",
    "Docker": "devops", "Kubernetes": "devops", "Terraform": "devops", "CI/CD": "devops",
    "OpenShift": "devops", "Helm": "devops", "Ansible": "devops", "Prometheus": "devops",
    "Spark": "data", "Airflow": "data", "Pandas": "data", "Snowflake": "data", "BigQuery": "data",
    "PyTorch": "ml", "TensorFlow": "ml", "NLP": "ml", "Computer Vision": "ml", "Machine Learning": "ml",
    "AI": "ml", "LLM": "ml", "Deep Learning": "ml", "Algorithms": "ml",
    "FastAPI": "backend", "Django": "backend", "Flask": "backend", "Spring": "backend",
    "Node.js": "backend", "NestJS": "backend", "Express": "backend", "gRPC": "backend",
    "QA/Automation": "qa", "Cybersecurity": "security", "Penetration Testing": "security",
    "Product Management": "product", "UX/UI": "design",
}


def families_of(text: str, limit: int = 4) -> set[str]:
    tl = _lc(text)
    found = {fam for fam, signs in FAMILY_SIGNS.items() if any(_contains(tl, s) for s in signs)}
    return set(list(found)[:limit])


def job_family(job) -> set[str]:
    fams = families_of(getattr(job, "title", ""))
    return fams or {"software"} if _contains(_lc(getattr(job, "title", "")), "engineer") else fams


def candidate_families(profile: dict) -> set[str]:
    text = f"{profile.get('headline','')} {' '.join(profile.get('titles', []))}"
    fams = families_of(text)
    for s in profile.get("skills", []):
        if s in _SKILL_FAMILY:
            fams.add(_SKILL_FAMILY[s])
    # drop management as a *candidate* family so we key off the craft, not the title
    fams.discard("management")
    return fams


def alignment(cand_fams: set[str], job_fams: set[str]) -> float:
    """1.0 = same family, ~0.7 adjacent, ~0.5 both engineering, ~0.2 unrelated."""
    if not cand_fams or not job_fams:
        return 0.85  # unknown -> mild, don't over-penalize
    if cand_fams & job_fams:
        return 1.0
    if any(job_fams & _ADJ.get(cf, set()) for cf in cand_fams):
        return 0.7
    if cand_fams & ENGINEERING and job_fams & ENGINEERING:
        return 0.5
    if cand_fams & ENGINEERING and not (job_fams & ENGINEERING):
        return 0.18  # engineer shown a non-engineering role -> strongly demote
    return 0.4
