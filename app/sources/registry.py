"""Build the set of active connectors from the packaged companies.yaml."""
from __future__ import annotations

import logging

import yaml

from app import config
from app.sources.ashby import AshbyConnector
from app.sources.base import Connector
from app.sources.comeet import ComeetConnector
from app.sources.greenhouse import GreenhouseConnector
from app.sources.jsearch import JSearchConnector
from app.sources.lever import LeverConnector
from app.sources.smartrecruiters import SmartRecruitersConnector

log = logging.getLogger(__name__)


ATS_KEYS = ("greenhouse", "lever", "ashby", "comeet", "smartrecruiters")


def load_companies() -> dict:
    if not config.COMPANIES_FILE.exists():
        # Without this file there are no company boards to scan, so every search
        # comes back empty. Loud on purpose — it is otherwise invisible.
        log.error("companies file missing at %s — no job boards to scan", config.COMPANIES_FILE)
        return {}
    with open(config.COMPANIES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def board_count() -> int:
    """How many company job boards are configured across all ATS sources."""
    cfg = load_companies()
    return sum(len(cfg.get(k) or []) for k in ATS_KEYS)


def build_connectors() -> list[Connector]:
    cfg = load_companies()
    connectors: list[Connector] = []

    if cfg.get("greenhouse"):
        connectors.append(GreenhouseConnector(cfg["greenhouse"]))
    if cfg.get("lever"):
        connectors.append(LeverConnector(cfg["lever"]))
    if cfg.get("ashby"):
        connectors.append(AshbyConnector(cfg["ashby"]))
    if cfg.get("comeet"):
        connectors.append(ComeetConnector(cfg["comeet"]))
    if cfg.get("smartrecruiters"):
        connectors.append(SmartRecruitersConnector(cfg["smartrecruiters"]))

    if not connectors:
        log.error(
            "no ATS boards configured (companies file: %s) — searches will return nothing",
            config.COMPANIES_FILE,
        )

    # JSearch is query-driven and always included; it self-skips without a key.
    connectors.append(JSearchConnector())

    return connectors


def default_queries() -> list[str]:
    cfg = load_companies()
    return cfg.get("jsearch_default_queries", ["software engineer"])
