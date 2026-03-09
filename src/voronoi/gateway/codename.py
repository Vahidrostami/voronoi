"""Investigation codename generator — brain-themed naming for investigations.

Each investigation gets a memorable neurotransmitter-based codename instead
of a bare numeric ID.  The codename is picked deterministically from
``inv_id`` so it's stable across restarts, but can also be overridden by
the classifier when an LLM is available to choose a thematically fitting name.
"""

from __future__ import annotations

# Codename pool — neurotransmitters / neurochemicals with thematic hints.
# The orchestrator prompt includes the theme so the LLM can riff on it.
CODENAMES: list[dict[str, str]] = [
    {"name": "Dopamine",        "theme": "reward, building, optimization"},
    {"name": "Serotonin",       "theme": "stability, balance, well-being"},
    {"name": "GABA",            "theme": "filtering, noise reduction, simplification"},
    {"name": "Glutamate",       "theme": "learning, exploration, new connections"},
    {"name": "Oxytocin",        "theme": "integration, collaboration, bonding"},
    {"name": "Endorphin",       "theme": "resilience, recovery, pushing through"},
    {"name": "Acetylcholine",   "theme": "memory, attention, deep focus"},
    {"name": "Norepinephrine",  "theme": "alertness, urgency, fight-or-flight"},
    {"name": "Anandamide",      "theme": "creativity, discovery, unexpected insight"},
    {"name": "Adrenaline",      "theme": "speed, performance, crisis response"},
    {"name": "Melatonin",       "theme": "cycles, timing, scheduling"},
    {"name": "Cortisol",        "theme": "stress response, debugging, fire-fighting"},
    {"name": "Histamine",       "theme": "defense, security, immune response"},
    {"name": "Glycine",         "theme": "simplification, minimalism, reduction"},
]

CODENAME_NAMES: list[str] = [c["name"] for c in CODENAMES]


def codename_for_id(inv_id: int) -> str:
    """Deterministic codename from an investigation ID (fallback)."""
    return CODENAME_NAMES[inv_id % len(CODENAME_NAMES)]


def theme_for_codename(name: str) -> str:
    """Return the thematic description for a codename."""
    for c in CODENAMES:
        if c["name"].lower() == name.lower():
            return c["theme"]
    return ""


def codename_pool_prompt() -> str:
    """Return a formatted prompt fragment listing all codenames + themes.

    Designed to be injected into the classifier LLM prompt so it can
    pick the best-fitting codename for a given investigation.
    """
    lines = ["Pick the most thematically fitting codename from this list:\n"]
    for c in CODENAMES:
        lines.append(f"- {c['name']} ({c['theme']})")
    return "\n".join(lines)
