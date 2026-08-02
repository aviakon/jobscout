"""Per-job cover letter + resume-tweak suggestions.

Offline template-based generation (English or Hebrew, chosen by the job's
language) so it works with zero setup; auto-upgrades to Claude when a key is set.
"""
from __future__ import annotations

import logging
import re

from app import config
from app.matching.heuristic_scorer import _skills_in
from app.models import Job
from app.resume.heuristic import _lc

log = logging.getLogger(__name__)

_HEB_RE = re.compile(r"[֐-׿]")


def _is_hebrew(job: Job) -> bool:
    return bool(_HEB_RE.search(f"{job.title} {job.description}"))


def _relevant_skills(profile: dict, job: Job) -> tuple[list[str], list[str]]:
    profile_skills = list(profile.get("skills", []))
    pset = set(profile_skills)
    job_skills = _skills_in(_lc(f"{job.title} {job.description}"))
    matching = [s for s in profile_skills if s in job_skills]      # keep profile order
    gaps = sorted(job_skills - pset)
    return matching[:6], gaps[:5]


# --- offline templates --------------------------------------------------------

def _letter_en(profile: dict, job: Job, matching: list[str]) -> str:
    name = profile.get("name") or "[Your name]"
    headline = profile.get("headline") or "professional"
    seniority = profile.get("seniority", "experienced")
    years = profile.get("total_years_experience")
    years_txt = f"{int(years)} years of " if years else ""
    skills_txt = ", ".join(matching[:4]) if matching else "the core skills this role calls for"
    extra = ", ".join(matching[4:6])
    extra_line = (
        f" I also bring hands-on experience with {extra}, which maps directly to your stack."
        if extra else ""
    )
    return f"""Dear {job.company} Hiring Team,

I'm writing to apply for the {job.title} position at {job.company}. As a {seniority} {headline} with {years_txt}experience, I was excited to see this opening. It aligns closely with my background.

My strongest overlap with what you're looking for is in {skills_txt}.{extra_line} Across my roles I've focused on building reliable, well-architected systems and delivering measurable results, and I'm confident I could do the same for your team.

I'd welcome the chance to discuss how my experience can contribute to {job.company}'s goals. Thank you for your time and consideration.

Best regards,
{name}"""


def _letter_he(profile: dict, job: Job, matching: list[str]) -> str:
    name = profile.get("name") or "[השם שלך]"
    headline = profile.get("headline") or "איש/אשת מקצוע"
    years = profile.get("total_years_experience")
    years_txt = f"עם {int(years)} שנות ניסיון " if years else ""
    skills_txt = ", ".join(matching[:4]) if matching else "בכישורים הנדרשים למשרה"
    return f"""לכבוד צוות הגיוס של {job.company},

אני פונה בעניין משרת {job.title} אצל {job.company}. כ{headline} {years_txt}התלהבתי לראות את המשרה. היא מתאימה מאוד לרקע המקצועי שלי.

החפיפה החזקה ביותר שלי עם הדרישות היא ב{skills_txt}. לאורך התפקידים שלי התמקדתי בבניית מערכות אמינות ובהשגת תוצאות מדידות, ואני משוכנע/ת שאוכל לתרום זאת גם לצוות שלכם.

אשמח להזדמנות לשוחח על האופן שבו הניסיון שלי יכול לתרום לחברת {job.company}. תודה על זמנכם.

בברכה,
{name}"""


def _tweaks_en(profile: dict, job: Job, matching: list[str], gaps: list[str]) -> list[str]:
    tips: list[str] = []
    if matching:
        tips.append(f"Move these matching skills to the top of your resume: {', '.join(matching[:5])}.")
    if job.title and job.title.lower() not in (profile.get("headline") or "").lower():
        tips.append(f"Mirror the exact job title \"{job.title}\" in your headline/summary for ATS keyword match.")
    if gaps:
        tips.append(f"The posting mentions {', '.join(gaps)}. If you have any exposure, add it explicitly.")
    tips.append("Quantify 2 to 3 achievements with concrete metrics (%, scale, revenue, latency).")
    tips.append(f"Add one line tailored to {job.company}'s domain to show you researched them.")
    return tips


def _tweaks_he(profile: dict, job: Job, matching: list[str], gaps: list[str]) -> list[str]:
    tips: list[str] = []
    if matching:
        tips.append(f"העבירו את הכישורים המתאימים לראש קורות החיים: {', '.join(matching[:5])}.")
    if job.title:
        tips.append(f"שלבו את שם המשרה המדויק \"{job.title}\" בכותרת/תקציר להתאמת מילות מפתח (ATS).")
    if gaps:
        tips.append(f"המשרה מזכירה {', '.join(gaps)}. אם יש לכם היכרות, ציינו זאת במפורש.")
    tips.append("כמתו 2 עד 3 הישגים עם מספרים קונקרטיים (אחוזים, היקף, הכנסה, ביצועים).")
    return tips


# --- LLM path -----------------------------------------------------------------

_LLM_SYSTEM = """You are an expert career coach. Given a candidate profile and a job
posting, write (1) a concise, specific cover letter (max ~200 words, no clichés,
no invented facts) and (2) 3-5 concrete resume-tailoring tips. Write in the job's
language (Hebrew or English). Do not use em-dashes or en-dashes; use periods or
commas instead. Return ONLY JSON: {"letter": string, "tweaks": [string]}."""


def _generate_llm(profile: dict, job: Job) -> dict | None:
    import json

    from anthropic import Anthropic
    from app.resume.parser import _loads_lenient

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = (
        f"CANDIDATE:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"JOB:\nTitle: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n"
        f"Description:\n{job.description[:5000]}"
    )
    try:
        msg = client.messages.create(
            model=config.SCORING_MODEL, max_tokens=1200,
            system=_LLM_SYSTEM, messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        data = _loads_lenient(text)
        if data.get("letter"):
            return {
                "letter": data["letter"],
                "tweaks": [str(t) for t in data.get("tweaks", [])][:5],
                "engine": "llm",
            }
    except Exception as e:
        log.warning("LLM cover letter failed (%s) — using offline template", e)
    return None


# --- public API ---------------------------------------------------------------

def generate(profile: dict, job: Job) -> dict:
    """Return {'letter', 'tweaks', 'engine', 'lang'} for this candidate + job."""
    if config.ANTHROPIC_API_KEY:
        llm = _generate_llm(profile, job)
        if llm:
            llm["lang"] = "he" if _is_hebrew(job) else "en"
            return llm

    matching, gaps = _relevant_skills(profile, job)
    if _is_hebrew(job):
        return {
            "letter": _letter_he(profile, job, matching),
            "tweaks": _tweaks_he(profile, job, matching, gaps),
            "engine": "heuristic", "lang": "he",
        }
    return {
        "letter": _letter_en(profile, job, matching),
        "tweaks": _tweaks_en(profile, job, matching, gaps),
        "engine": "heuristic", "lang": "en",
    }
