"""GitHub Publisher — push investigation results to GitHub.

Creates a repo per investigation under a configured GitHub org,
pushes all code/data/deliverables, and creates Issues for findings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from voronoi.beads import run_cmd as _run_cmd


class GitHubPublisher:
    """Publishes investigation results to GitHub repos."""

    def __init__(self, lab_org: str = "voronoi-lab", visibility: str = "private"):
        self.lab_org = lab_org
        self.visibility = visibility

    def is_gh_available(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        code, _ = _run_cmd(["gh", "auth", "status"])
        return code == 0

    def publish(
        self,
        workspace_path: str,
        repo_name: str,
        description: str = "",
    ) -> tuple[bool, str]:
        """Publish a workspace to a GitHub repo.

        1. Creates the repo if it doesn't exist
        2. Adds remote and pushes
        Returns (success, url_or_error).
        """
        full_repo = f"{self.lab_org}/{repo_name}"

        # 1. Create repo if needed
        code, output = _run_cmd([
            "gh", "repo", "create", full_repo,
            f"--{self.visibility}",
            "--description", description or f"Voronoi investigation: {repo_name}",
            "--source", workspace_path,
            "--push",
        ], cwd=workspace_path)

        if code == 0:
            url = f"https://github.com/{full_repo}"
            return True, url

        # Repo might already exist — try just pushing
        code2, _ = _run_cmd([
            "git", "remote", "add", "voronoi-lab",
            f"https://github.com/{full_repo}.git",
        ], cwd=workspace_path)

        code3, output3 = _run_cmd([
            "git", "push", "voronoi-lab", "main", "--force",
        ], cwd=workspace_path, timeout=120)

        if code3 == 0:
            url = f"https://github.com/{full_repo}"
            return True, url

        return False, f"Failed to publish: {output} | {output3}"

    def create_finding_issues(
        self,
        repo_name: str,
        findings: list[dict],
    ) -> list[str]:
        """Create GitHub Issues for investigation findings.

        Each finding becomes a labeled Issue in the investigation repo.
        Returns list of created issue URLs.
        """
        full_repo = f"{self.lab_org}/{repo_name}"
        urls = []

        for finding in findings:
            title = finding.get("title", "Finding")
            body_parts = []
            for key in ("effect_size", "confidence_interval", "sample_size",
                        "stat_test", "valence", "robust"):
                val = finding.get(key)
                if val:
                    body_parts.append(f"**{key}**: {val}")
            if finding.get("notes"):
                body_parts.append(f"\n```\n{finding['notes']}\n```")

            body = "\n".join(body_parts) or "See deliverable.md for details."

            code, output = _run_cmd([
                "gh", "issue", "create",
                "--repo", full_repo,
                "--title", title,
                "--body", body,
                "--label", "finding",
            ])
            if code == 0:
                urls.append(output.strip())

        return urls
