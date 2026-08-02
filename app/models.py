"""Database models: Candidate, Job, Match."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_public_id() -> str:
    """Unguessable per-candidate token used in URLs instead of the sequential
    integer id — so a candidate's page/data can't be found by enumeration."""
    return secrets.token_urlsafe(16)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=new_public_id)
    name: Mapped[str] = mapped_column(String(200), default="")
    resume_filename: Mapped[str] = mapped_column(String(400), default="")
    resume_text: Mapped[str] = mapped_column(Text, default="")
    profile_json: Mapped[str] = mapped_column(Text, default="{}")  # structured profile from Claude
    gap_analysis_json: Mapped[str] = mapped_column(Text, default="[]")  # recurring missing skills
    last_summary_json: Mapped[str] = mapped_column(Text, default="{}")  # last run stats
    skill_experience_json: Mapped[str] = mapped_column(Text, default="{}")  # {skill: years}
    preferences_json: Mapped[str] = mapped_column(Text, default="{}")  # search preferences
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    matches: Mapped[list[Match]] = relationship(back_populates="candidate", cascade="all, delete-orphan")

    @property
    def profile(self) -> dict:
        try:
            return json.loads(self.profile_json)
        except (ValueError, TypeError):
            return {}

    @property
    def gap_analysis(self) -> list[dict]:
        try:
            return json.loads(self.gap_analysis_json)
        except (ValueError, TypeError):
            return []

    @property
    def last_summary(self) -> dict:
        try:
            return json.loads(self.last_summary_json)
        except (ValueError, TypeError):
            return {}

    @property
    def skill_experience(self) -> dict:
        try:
            return json.loads(self.skill_experience_json)
        except (ValueError, TypeError):
            return {}

    @property
    def preferences(self) -> dict:
        try:
            return json.loads(self.preferences_json)
        except (ValueError, TypeError):
            return {}


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(400))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(50))  # comeet / greenhouse / lever / ashby / jsearch
    remote: Mapped[str] = mapped_column(String(20), default="")  # remote / hybrid / onsite / ""
    posted_at: Mapped[str] = mapped_column(String(50), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    matches: Mapped[list[Match]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", name="uq_match_candidate_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)

    score: Mapped[float] = mapped_column(Float, default=0.0)          # 0-100 LLM score
    prefilter_score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(500), default="")
    why_json: Mapped[str] = mapped_column(Text, default="[]")    # why-you-match bullets
    gaps_json: Mapped[str] = mapped_column(Text, default="[]")   # what's-missing bullets
    status: Mapped[str] = mapped_column(String(20), default="new")  # new / saved / applied / hidden
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    candidate: Mapped[Candidate] = relationship(back_populates="matches")
    job: Mapped[Job] = relationship(back_populates="matches")

    @property
    def why(self) -> list[str]:
        try:
            return json.loads(self.why_json)
        except (ValueError, TypeError):
            return []

    @property
    def gaps(self) -> list[str]:
        try:
            return json.loads(self.gaps_json)
        except (ValueError, TypeError):
            return []
