"""Resume parsing: file bytes -> text -> structured candidate profile via Claude."""
from __future__ import annotations

import io
import json
import logging

from app import config

log = logging.getLogger(__name__)


def _space_ratio(text: str) -> float:
    """Fraction of characters that are spaces — a proxy for extraction quality.
    Well-extracted prose is ~0.12–0.18; space-stripped PDFs are near 0."""
    if not text:
        return 0.0
    return text.count(" ") / len(text)


def extract_text(filename: str, data: bytes) -> str:
    """Extract raw text from a PDF, DOCX, or plain-text resume.

    Some PDFs extract with spaces stripped (e.g. 'SHACHARMARGALIT'), which breaks
    downstream skill matching. We try pypdf's layout mode first (best spacing),
    fall back to the default mode, and keep whichever preserved more spaces.
    """
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))

        def _extract(mode: str | None) -> str:
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text(extraction_mode=mode) if mode
                                 else page.extract_text() or "")
                except Exception:  # noqa: BLE001
                    parts.append("")
            return "\n".join(p or "" for p in parts)

        layout = _extract("layout")
        if _space_ratio(layout) >= 0.07:
            return layout
        default = _extract(None)
        # keep whichever has more spaces (better word separation)
        best = max(layout, default, key=_space_ratio)
        log.info("pdf extraction space-ratio layout=%.3f default=%.3f",
                 _space_ratio(layout), _space_ratio(default))
        return best
    if name.endswith(".docx"):
        import docx

        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    # txt / md / fallback
    return data.decode("utf-8", errors="ignore")


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def is_image(filename: str) -> bool:
    return filename.lower().endswith(_IMAGE_EXTS)


def _media_type(filename: str) -> str:
    n = filename.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _ocr_offline(data: bytes) -> str:
    """OCR an image with the built-in Windows OCR engine (no API key, no external
    binary). Returns '' if unavailable or it finds nothing."""
    try:
        import asyncio
        import threading

        import winocr
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        # upscale small images — OCR is much better at higher resolution
        if max(img.size) < 1600:
            scale = 1600 / max(img.size)
            img = img.resize((int(img.width * scale), int(img.height * scale)))
    except Exception as e:  # noqa: BLE001
        log.info("offline OCR unavailable: %s", e)
        return ""

    async def _run() -> str:
        for lang in ("en", None):
            try:
                res = await (winocr.recognize_pil(img, lang) if lang else winocr.recognize_pil(img))
                if res and res.text.strip():
                    # preserve line breaks (needed for role/date/education parsing)
                    try:
                        return "\n".join(ln.text for ln in res.lines)
                    except Exception:  # noqa: BLE001
                        return res.text
            except Exception:  # noqa: BLE001
                continue
        return ""

    box: dict = {}

    def _worker() -> None:
        try:
            box["t"] = asyncio.run(_run())
        except Exception as e:  # noqa: BLE001
            log.info("offline OCR failed: %s", e)

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    return box.get("t", "") or ""


def _claude_vision(filename: str, data: bytes) -> str:
    import base64

    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(data).decode()
    msg = client.messages.create(
        model=config.PARSING_MODEL,
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": _media_type(filename), "data": b64}},
                {"type": "text", "text": "Transcribe all text from this resume image, preserving order. Output only the text."},
            ],
        }],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def extract_text_from_image(filename: str, data: bytes) -> str:
    """Read text from a resume photo.

    Uses Claude vision when a key is set (most accurate); otherwise falls back to
    the offline Windows OCR engine so photos work with zero setup on Windows."""
    if config.ANTHROPIC_API_KEY:
        try:
            text = _claude_vision(filename, data)
            if text.strip():
                return text
        except Exception as e:  # noqa: BLE001
            log.warning("Claude vision failed (%s) — trying offline OCR", e)

    text = _ocr_offline(data)
    if text.strip():
        return text

    raise RuntimeError(
        "לא הצלחנו לקרוא טקסט מהתמונה. נסו תמונה ברורה יותר, "
        "העלו קובץ PDF/DOCX, או הדביקו את הטקסט."
    )


def fetch_resume_from_url(url: str) -> str:
    """Best-effort: fetch a public resume page/PDF and return its text."""
    import re

    import httpx

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "linkedin.com" in url.lower():
        raise RuntimeError(
            "לא ניתן לייבא מ-LinkedIn (מדיניות השירות). "
            "השתמשו בקישור לאתר אישי / קובץ PDF, או הדביקו טקסט."
        )
    resp = httpx.get(url, timeout=20, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (JobScout resume import)"})
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return extract_text("resume.pdf", resp.content)
    html = resp.text
    html = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    return re.sub(r"[ \t]*\n[ \t\n]*", "\n", re.sub(r"[ \t]+", " ", text)).strip()


PROFILE_SYSTEM = """You perform a THOROUGH, accurate analysis of a resume for job matching.
The resume may be in Hebrew or English. Respond in the resume's primary language for
free-text fields. Analyze every role and its dates carefully. Return ONLY valid JSON,
no prose, matching this schema:
{
  "name": string,
  "headline": string,                 // e.g. "Senior Backend Engineer"
  "seniority": string,                // intern | junior | mid | senior | lead | manager | director
  "total_years_experience": number,   // total professional (non-military-command) years
  "skills": [string],                 // EVERY concrete skill/technology in the resume, most important first
  "skill_years": { string: number },  // years of experience per skill, from the dates of the roles that used it
  "titles": [string],                 // job titles held or clearly targetable
  "experiences": [                     // one entry per dated role
    { "title": string, "start": number, "end": number, "years": number, "is_military": boolean }
  ],
  "industries": [string],
  "languages": [string],
  "locations": [string],              // cities/countries the person can work in
  "remote_pref": string,              // remote | hybrid | onsite | any
  "summary": string
}

Critical rules for accurate seniority:
- Compute per-skill years from role date ranges (e.g. an engineer 2019-2025 who used
  Python throughout => ~6 years of Python).
- Do NOT inflate seniority from MILITARY leadership. A short stint as an army "team lead"
  or officer does NOT make someone a civilian team lead/manager — military experience is
  different and often brief. Only grant "lead"/"manager" for sustained (>=1.5y) CIVILIAN
  management. Otherwise base the level on technical years (junior<2, mid 2-5, senior 5+)."""


def parse_profile(resume_text: str) -> dict:
    """Turn resume text into a structured profile dict.

    Uses Claude when ANTHROPIC_API_KEY is set; otherwise falls back to a fully
    offline heuristic parser so JobScout works with zero setup.
    """
    if not config.ANTHROPIC_API_KEY:
        from app.resume.heuristic import build_profile

        log.info("no API key — parsing resume with offline heuristic engine")
        return build_profile(resume_text)

    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model=config.PARSING_MODEL,
            max_tokens=2000,
            system=PROFILE_SYSTEM,
            messages=[{"role": "user", "content": resume_text[:20000]}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        profile = _loads_lenient(text)
        if profile:
            profile.setdefault("_engine", "llm")
            return profile
    except Exception as e:
        log.warning("LLM parse failed (%s) — falling back to heuristic", e)

    from app.resume.heuristic import build_profile

    return build_profile(resume_text)


def _loads_lenient(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error("failed to parse profile JSON: %s", e)
        return {}
