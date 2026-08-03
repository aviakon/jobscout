"""Sponsored slots shown above the job matches.

Paid ads live in a YAML file (`app/resources/sponsors.yaml`, overridable with
`SPONSORS_FILE` or a `data/sponsors.yaml` copy), so selling a slot is a config
change and never a code change. Any slot not sold falls back to a house ad
inviting companies to get in touch, so the strip is never empty and never
looks broken.

Sponsored slots are deliberately kept OUT of the match list: they are not
scored against the resume, are not counted in the match stats, and the filter
and sort toolbar never touches them. A paid placement must not be able to
masquerade as a genuine ranked match.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import yaml

from app import config

log = logging.getLogger(__name__)


@dataclass
class Ad:
    slug: str                      # stable id, used for click/impression stats
    title: str
    company: str = ""
    body: str = ""
    url: str = ""
    location: str = ""
    logo: str = ""                 # an emoji, so no external image requests
    paid: bool = True
    starts_on: str = ""            # optional YYYY-MM-DD campaign window
    ends_on: str = ""
    roles: list[str] = field(default_factory=list)  # optional targeting keywords

    @property
    def is_house_ad(self) -> bool:
        return not self.paid


def _within_campaign_window(ad: Ad, today: date) -> bool:
    for value, is_start in ((ad.starts_on, True), (ad.ends_on, False)):
        if not value:
            continue
        try:
            when = date.fromisoformat(str(value))
        except ValueError:
            log.warning("sponsor %s has an unreadable date %r, ignoring it", ad.slug, value)
            continue
        if is_start and today < when:
            return False
        if not is_start and today > when:
            return False
    return True


def _matches_targeting(ad: Ad, profile_terms: str) -> bool:
    """An ad with no `roles` is untargeted and shows to everyone."""
    if not ad.roles:
        return True
    return any(r.strip().lower() in profile_terms for r in ad.roles if r.strip())


def load_sponsors() -> list[Ad]:
    path = config.SPONSORS_FILE
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        log.warning("could not read sponsors file %s: %s", path, e)
        return []

    ads: list[Ad] = []
    for entry in raw.get("sponsors") or []:
        if not isinstance(entry, dict) or not entry.get("title"):
            continue
        if entry.get("active") is False:
            continue
        known = {f for f in Ad.__dataclass_fields__ if f != "paid"}
        ads.append(Ad(paid=True, **{k: v for k, v in entry.items() if k in known}))
    return ads


def house_ad(index: int = 0) -> Ad:
    """Placeholder for an unsold slot: an invitation to advertise."""
    return Ad(
        slug=f"house-{index}",
        title="רוצים לפרסם כאן?",
        company="",
        body="המקום הזה פנוי למודעות של חברות. מחפשים מועמדים? השאירו פרטים "
             "והמודעה שלכם תופיע כאן, ראשונה, מול כל מי שמחפש עבודה.",
        # an on-site form, not a mailto: a mail link silently does nothing for
        # visitors whose browser has no mail client, and loses the lead
        url="/advertise",
        logo="📣",
        paid=False,
    )


def slots_for(profile: dict | None = None, count: int | None = None) -> list[Ad]:
    """The ad strip: paying sponsors first, then a single invitation to advertise.

    Only ever ONE house ad, however many slots are unsold — the same "advertise
    here" card repeated looks like a rendering fault, not like inventory.
    """
    count = config.AD_SLOTS if count is None else count
    if count <= 0:
        return []

    terms = ""
    if profile:
        terms = " ".join(
            [profile.get("headline", "") or ""]
            + list(profile.get("titles", []) or [])
            + list(profile.get("skills", []) or [])
        ).lower()

    today = date.today()
    sponsors = [
        ad for ad in load_sponsors()
        if _within_campaign_window(ad, today) and _matches_targeting(ad, terms)
    ][:count]

    if len(sponsors) >= count:
        return sponsors
    return sponsors + [house_ad(0)]
