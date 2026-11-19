"""Shared data models for the Automated PR Assistant.

This is the contract between the modules. Field names for PullRequestSummary
follow the output schema in the problem statement (output/pr_summaries.json).
Change a field here only after telling the other developers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ChangedFile:
    """One file changed in a pull request (from the get-PR-files tool)."""

    filename: str
    additions: int = 0
    deletions: int = 0
    status: str = "modified"  # added | modified | removed | renamed

    @property
    def changes(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class PullRequest:
    """An open pull request as returned by mcp_client.list_open_prs."""

    number: int
    title: str
    author: str
    url: str
    head_branch: str = ""
    base_branch: str = ""
    files: tuple[ChangedFile, ...] = ()

    @property
    def changed_files(self) -> list[str]:
        return [f.filename for f in self.files]

    @property
    def total_changed_lines(self) -> int:
        return sum(f.changes for f in self.files)


@dataclass(frozen=True)
class RiskAssessment:
    """Output of risk.py: a level plus the rules that triggered it."""

    level: RiskLevel
    reasons: tuple[str, ...] = ()


@dataclass
class PullRequestSummary:
    """One entry in output/pr_summaries.json (written by report.py)."""

    number: int
    title: str
    author: str
    url: str
    changed_files: list[str]
    risk: RiskAssessment
    suggested_reviewers: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "changed_files": list(self.changed_files),
            "risk": {"level": str(self.risk.level), "reasons": list(self.risk.reasons)},
            "suggested_reviewers": list(self.suggested_reviewers),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Branch:
    """A branch as returned by mcp_client.list_branches.

    last_commit_date is filled in by mcp_client.get_commit_date.
    pr_number / pr_merged are filled in by branches.py when it matches the
    branch to its pull request.
    """

    name: str
    sha: str = ""
    protected: bool = False
    is_fork: bool = False
    last_commit_date: datetime | None = None
    pr_number: int | None = None
    pr_merged: bool = False


@dataclass(frozen=True)
class BranchDecision:
    """Eligibility result for one branch (branches.py), shown in the dry-run table."""

    branch: Branch
    eligible: bool
    reason: str  # e.g. "merged, 12 days old" or "protected branch"
    age_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        last = self.branch.last_commit_date
        data["branch"]["last_commit_date"] = last.isoformat() if last else None
        return data
