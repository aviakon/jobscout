"""Build the set of active connectors from data/companies.yaml."""
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

log = logging.getLogger(__name__)


def load_companies() -> dict:
    if not config.COMPANIES_FILE.exists():
        return {}
    with open(config.COMPANIES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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

    # JSearch is query-driven and always included; it self-skips without a key.
    connectors.append(JSearchConnector())

    return connectors


def default_queries() -> list[str]:
    cfg = load_companies()
    return cfg.get("jsearch_default_queries", ["software engineer"])
