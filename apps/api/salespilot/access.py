"""Role + page-policy system.

Five known groups (gradient from most to least privileged):
    administrators    -- alle pagina's en alle acties
    financieel        -- alles waar financiele cijfers in zitten
    sales             -- acquisitie + outreach + offertes lezen
    marketing         -- acquisitie + outreach
    agendagebruikers  -- persoonlijke agenda (Lisa)

A user can belong to multiple groups. Page-level policies are defined
in `PAGE_POLICIES` below as a single source of truth that both backend
(FastAPI dependency) and frontend (sidebar visibility) consult.

Two dimensions:
  - "sections" -- coarse buckets aligned with sidebar groups
  - explicit per-route overrides for one-off pages

A user is granted a section if their groups[] intersects with the
section's allowed_groups. Admins always pass.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from fastapi import HTTPException


# ---------------------------------------------------------------------
# Known groups
# ---------------------------------------------------------------------


class Group(str, Enum):
    ADMINISTRATORS = "administrators"
    FINANCIEEL = "financieel"
    SALES = "sales"
    MARKETING = "marketing"
    AGENDAGEBRUIKERS = "agendagebruikers"


KNOWN_GROUPS: tuple[str, ...] = tuple(g.value for g in Group)


# ---------------------------------------------------------------------
# Section policy (used by both backend + frontend)
# ---------------------------------------------------------------------


# Each section has a sidebar label, an allowlist of groups, and a list
# of route-prefixes that fall under it. Admins implicitly pass every
# section.

SECTIONS: dict[str, dict] = {
    "core": {
        "label": "Algemeen",
        "allowed_groups": {"administrators", "marketing", "sales", "financieel", "agendagebruikers"},
        "routes": ["/dashboard"],
    },
    "acquisitie": {
        "label": "Acquisitie + Outreach",
        "allowed_groups": {"administrators", "marketing", "sales"},
        "routes": [
            "/companies", "/contacts", "/deals", "/activities",
            "/wespennest", "/toegekend",
            "/sequences", "/social", "/linkedin", "/mail-campaigns",
        ],
    },
    "financieel": {
        "label": "Financieel",
        "allowed_groups": {"administrators", "financieel"},
        "routes": [
            "/quotations",
            "/financieel",
            "/mandates",
        ],
    },
    "monitoring": {
        "label": "Monitoring",
        "allowed_groups": {"administrators"},
        "routes": ["/unifi"],
    },
    "tech": {
        "label": "Tech",
        "allowed_groups": {"administrators"},
        "routes": ["/tech"],
    },
    "agenda": {
        "label": "Persoonlijke agenda",
        "allowed_groups": {"administrators", "agendagebruikers"},
        "routes": ["/calendar"],
    },
    "settings": {
        "label": "Instellingen",
        "allowed_groups": {"administrators"},
        "routes": ["/settings"],
    },
}


# ---------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------


def user_can_access_section(user_groups: Iterable[str], section: str) -> bool:
    """True if the user's groups intersect with the section's allowlist
    (or the user is administrator)."""
    s = set(user_groups or [])
    if "administrators" in s:
        return True
    section_def = SECTIONS.get(section)
    if section_def is None:
        return False
    return bool(s & set(section_def["allowed_groups"]))


def user_can_access_route(user_groups: Iterable[str], path: str) -> bool:
    """True if any route-prefix in any allowed section matches `path`."""
    s = set(user_groups or [])
    if "administrators" in s:
        return True
    for section_id, sec in SECTIONS.items():
        if not (s & set(sec["allowed_groups"])):
            continue
        for prefix in sec["routes"]:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
                return True
    return False


def visible_sections(user_groups: Iterable[str]) -> list[str]:
    """Section IDs the user is allowed to see. Used by the frontend
    to hide sidebar groups they have no business in."""
    return [
        sid for sid in SECTIONS
        if user_can_access_section(user_groups, sid)
    ]


def require_groups(*allowed: str):
    """FastAPI dependency factory. Use as:
        Depends(require_groups("administrators"))
        Depends(require_groups("administrators", "financieel"))
    """
    allowed_set = set(allowed) | {"administrators"}

    def _checker(auth) -> None:
        user_groups = set(getattr(auth, "groups", []) or [])
        if not (user_groups & allowed_set):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Onvoldoende rechten. Vereist: {', '.join(sorted(allowed_set))}; "
                    f"jij hebt: {', '.join(sorted(user_groups)) or '(geen rol)'}"
                ),
            )

    return _checker
