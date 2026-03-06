"""Repo URL extractor — parse GitHub repository URLs from free text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Matches: github.com/owner/repo, https://github.com/owner/repo,
#          github.com/owner/repo.git, owner/repo (if looks like a repo)
_GH_URL_PATTERN = re.compile(
    r"(?:https?://)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?(?:\s|$|[?#])",
    re.I,
)

# Looser pattern: owner/repo when no github.com prefix (must have slash, no spaces)
_OWNER_REPO_PATTERN = re.compile(
    r"\b([a-zA-Z0-9_.-]{1,39})/([a-zA-Z0-9_.-]{1,100})\b"
)

# Words that look like owner/repo but aren't
_FALSE_POSITIVES = {
    "and/or", "w/o", "n/a", "i/o", "http/2", "tcp/ip",
    "true/false", "yes/no", "on/off", "input/output",
}


@dataclass(frozen=True)
class RepoRef:
    """A parsed GitHub repository reference."""
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"

    @property
    def slug(self) -> str:
        """Filesystem-safe slug for this repo."""
        return f"{self.owner}--{self.name}"


def extract_repo_url(text: str) -> Optional[RepoRef]:
    """Extract a GitHub repo reference from free text.

    Tries explicit github.com URLs first, then falls back to owner/repo patterns.
    Returns None if no repo is found.
    """
    # 1. Try explicit github.com URL
    m = _GH_URL_PATTERN.search(text)
    if m:
        return RepoRef(owner=m.group(1), name=m.group(2))

    # 2. Try owner/repo pattern (less confident)
    for m in _OWNER_REPO_PATTERN.finditer(text):
        candidate = m.group(0).lower()
        if candidate in _FALSE_POSITIVES:
            continue
        owner, name = m.group(1), m.group(2)
        # Heuristic: skip if owner or name is too short or looks like a path
        if len(owner) < 2 or len(name) < 2:
            continue
        if name.endswith((".py", ".js", ".ts", ".md", ".txt", ".sh")):
            continue
        return RepoRef(owner=owner, name=name)

    return None


def strip_repo_url(text: str) -> str:
    """Remove the repo URL from text, returning the question only."""
    text = _GH_URL_PATTERN.sub("", text).strip()
    return text
