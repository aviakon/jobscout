# 🧭 JobScout — AI Job-Matching Agent

Reads a resume, deeply searches the job market across **many sources**, and surfaces the
jobs that best fit the candidate — including "hidden" jobs that never reach LinkedIn.

Built for the **Israeli market first** (Hebrew + English, RTL UI). ToS-safe: it does **not**
scrape LinkedIn. LinkedIn postings still reach you indirectly via Google-for-Jobs aggregation.

## How it works

```
Resume (PDF/DOCX) → Claude → structured profile
        │
Sources → normalize → dedupe → keyword prefilter → Claude scores each job 0-100
 (Greenhouse, Lever, Ashby, Comeet, JSearch)              (why you match / what's missing)
        │
Web dashboard: ranked matches, reasons, gap analysis, save/applied tracking
```

## Sources
- **ATS public APIs** (free, no key): Greenhouse, Lever, Ashby, Comeet — the "hidden jobs" edge.
- **JSearch** (RapidAPI, free tier): aggregates Google for Jobs (LinkedIn, Indeed, AllJobs, Drushim).

Add target companies in [`app/resources/companies.yaml`](app/resources/companies.yaml).
(Files that ship with the code live in `app/resources/`; `data/` holds mutable state only,
because in production it is a mounted volume that would hide anything the image put there.)

## Two modes — works with **zero setup**

| | Resume parsing | Job scoring | Requires |
|---|---|---|---|
| **Offline (default)** | keyword/vocabulary heuristics (EN+HE) | skill/title/seniority overlap | nothing |
| **AI (auto-upgrade)** | Claude structured extraction | Claude 0–100 with nuanced reasons | `ANTHROPIC_API_KEY` |

It runs fully offline out of the box — no API keys, no accounts. Add `ANTHROPIC_API_KEY`
to `.env` and it automatically upgrades parsing + scoring to Claude. Add `RAPIDAPI_KEY`
to also pull from JSearch (Google-for-Jobs / LinkedIn coverage).

## Setup

```bash
pip install -r requirements.txt
```

Optional (to enable AI mode):

```bash
cp .env.example .env      # then fill in ANTHROPIC_API_KEY (and optionally RAPIDAPI_KEY)
```

## Try it immediately (offline, no keys)

```bash
python cli.py app/resources/sample_resume.txt --location Israel
```

## The web experience

- **Landing** (`/`) — an aurora / deep-space marketing page with a rotating headline and a
  **בואו נתחיל** call-to-action.
- **Onboarding** (`/start`) — a two-step wizard: **(1)** add your resume by **file, pasted text,
  photo, or link** (photos are read offline via the built-in Windows OCR engine — no key
  needed on Windows; LinkedIn links aren't supported per ToS), then
  **(2)** answer preference questions — desired salary, region, full/part-time, remote, target
  level, and roles of interest. Submitting scans the market and lands on your results.
- **Results** show a preferences summary (with **✎ ערוך העדפות** to change and re-run) and
  **fit badges** (✓ באזור שלך / ✓ מתאים לעבודה מהבית) on matches. Preferences steer the search:
  roles expand queries, region/remote filter, target level biases ranking.

## Run the web app

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 → upload a resume → click "search jobs".

## Run from the CLI

```bash
python cli.py path/to/resume.pdf --location Israel
```

## Daily digest — only *new* jobs

Re-scan the market and surface only matches you haven't seen before. The first run
shows all current matches; later runs show only jobs that appeared since.

```bash
python digest_cli.py                 # rescan, write HTML digests to data/digests/
python digest_cli.py --email         # also email (needs SMTP_* in .env)
```

In the web app, each candidate has a **📬 דיג'סט משרות חדשות** page showing new matches
with ✨ badges, a "rescan" button, and "mark all as read".

### Schedule it (Windows Task Scheduler)

Run the digest every morning at 08:00 — paste into an **elevated PowerShell** (edit the path):

```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "digest_cli.py" -WorkingDirectory "C:\Users\aviak\OneDrive\Desktop\work agent"
$trigger = New-ScheduledTaskTrigger -Daily -At 8am
Register-ScheduledTask -TaskName "JobScout Daily Digest" -Action $action -Trigger $trigger
```

(macOS/Linux: add `0 8 * * * cd /path/to/app && python digest_cli.py` via `crontab -e`.)

## Rate your experience per skill

On the candidate page, **click any skill chip** to open a circular gauge and set how
many years of experience you have (slider or −/+ buttons, auto-saved). Skills you rate
highly get a scoring boost on the next search, so matches lean toward roles built around
your real strengths. Rated skills show a green year badge (e.g. `Python 8y`).

> Note: experience affects the score on the **next** search/rescan — re-run the search
> after updating your ratings to see the re-ranked matches.

**Add missing skills by search:** type in the **➕ הוסף כישור** box under your skills to
search a built-in vocabulary (autocompletes as you type) or add a custom skill. New skills
become chips you can rate like any other. Remove a skill from inside its gauge (🗑️ הסר כישור).

## Cover letters + resume tweaks

Every match has a **✍️ מכתב מקדים** button that generates a tailored cover letter
(English or Hebrew, matched to the job's language) plus concrete resume-tailoring
tips for that specific role. Offline template-based by default; upgrades to Claude
when `ANTHROPIC_API_KEY` is set. Always review and personalize before sending.

## Test

```bash
pytest -q
```

## Publishing this publicly

There's no login system, so two things matter for a public URL:

- **Data isolation, not a login.** Every candidate is addressed by an unguessable
  token in the URL (`/candidate/<random-token>`), never a sequential id. The
  homepage never lists other people's profiles — it only shows "your profiles"
  based on a cookie set in your browser when you create one. Bookmark your link;
  there's no password recovery because there's no password.
- **Rate limiting.** `/onboard`, `/candidate/<id>/search`, and the digest rescan
  are capped per IP (in-memory, resets on restart) to stop the ~1-minute
  multi-source scan from being hammered. This is casual-abuse protection, not a
  defense against a determined attacker.

### Deploying to Railway

The live service deploys from GitHub. After the first setup, a `git push` is all
that's needed, **provided auto-deploy is on**:

> Railway → service → Settings → Source → "Branch connected to production".
> If it says **"Auto deploy is disabled"**, click **Enable**. Without it, pushes
> are silently ignored and the site keeps serving the old build even though
> Railway reports "Deployment successful" for the previous commit.

To deploy from this folder instead of GitHub:

```bash
railway login       # authorizes the CLI (use --browserless if the browser hangs)
railway link         # links this folder to the existing project
railway up            # builds and deploys
```

Then in the Railway dashboard for the service:
1. **Attach a Volume** mounted at `/app/data` — without this, the SQLite database
   (and everyone's résumés/matches) is wiped on every redeploy or restart.
2. **Environment variables** — only set `ANTHROPIC_API_KEY` if you also add real
   protection first (auth, spend limits). On a public, unauthenticated site, an
   API key means *any visitor* can run up your Anthropic bill. Left unset, the
   app runs entirely on the free offline engine — the safe default for a public
   launch.
3. Photo résumé upload uses the offline Windows OCR engine, which only exists on
   Windows — on Railway's Linux containers, photo upload will show the graceful
   "couldn't read that image" message unless `ANTHROPIC_API_KEY` is set (Claude
   vision). File upload, pasted text, and links all work regardless.

## Roadmap
- ✅ Phase 3: daily re-scan, "only new jobs" digest, optional email delivery.
- ✅ Cover-letter generator + per-job resume tweaks.
- ✅ Public deployment: token-based data isolation, rate limiting, Railway config.
- Phase 4: real accounts, Postgres, more sources (Comeet/AllJobs/Drushim), Telegram alerts.
