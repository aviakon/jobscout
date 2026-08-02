"""Application settings loaded from environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")

SCORING_MODEL: str = os.getenv("SCORING_MODEL", "claude-haiku-4-5-20251001")
PARSING_MODEL: str = os.getenv("PARSING_MODEL", "claude-sonnet-5")

# Optional email delivery for digests (all off unless configured)
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
DIGEST_TO: str = os.getenv("DIGEST_TO", "")          # recipient email
DIGEST_FROM: str = os.getenv("DIGEST_FROM", "") or SMTP_USER


def email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and DIGEST_TO)

# `data/` holds *mutable state only* (DB, uploads, digests). In production it is a
# mounted Railway volume, which overlays the directory and hides anything the image
# shipped inside it — so files that ship with the code live in `app/resources/`
# instead, where no volume can shadow them.
DATA_DIR = BASE_DIR / "data"
RESOURCES_DIR = BASE_DIR / "app" / "resources"
UPLOAD_DIR = DATA_DIR / "uploads"
DIGEST_DIR = DATA_DIR / "digests"
DB_PATH = DATA_DIR / "jobscout.db"

SAMPLE_RESUME = RESOURCES_DIR / "sample_resume.txt"


def _companies_file() -> Path:
    """Packaged company list, with an optional local override."""
    env = os.getenv("COMPANIES_FILE")
    if env:
        return Path(env)
    local = DATA_DIR / "companies.yaml"   # hand-edited local list wins, if present
    return local if local.exists() else RESOURCES_DIR / "companies.yaml"


COMPANIES_FILE = _companies_file()

# Matching pipeline knobs
PREFILTER_TOP_N = 90          # jobs scored (wider pool so level/location filters still leave enough)
SCORER_MAX_CONCURRENCY = 5    # parallel Claude calls
MIN_SCORE_TO_SHOW = 30        # hide matches below this score
MIN_RESULTS = 12              # always keep at least this many best matches

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
DIGEST_DIR.mkdir(exist_ok=True)
