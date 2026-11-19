"""Unit tests for mcp_client using a fake MCP session (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from config import Settings
from mcp_client import GitHubMCPClient, MCPError


def make_settings(per_page: int = 2) -> Settings:
    raw = {
        "github": {"mcp_url": "https://example.test/mcp/", "per_page": per_page},
        "risk": {},
        "reviewers": {"max_suggestions": 3},
        "cleanup": {"min_age_days": 7, "protected_branches": []},
        "output": {"dir": "output"},
    }
    return Settings(raw, "tok", "owner1", "repo1", "")


def result(payload, is_error: bool = False):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(is_error=is_error, content=[SimpleNamespace(text=text)])


class FakeSession:
    """Returns queued results per tool name and records every call."""

    def __init__(self, **queues):
        self.queues = {name: list(items) for name, items in queues.items()}
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return self.queues[name].pop(0)


def client_for(session, per_page: int = 2) -> GitHubMCPClient:
    return GitHubMCPClient(make_settings(per_page), session=session)


def pr_item(n: int):
    return {
        "number": n,
        "title": f"PR {n}",
        "html_url": f"https://github.com/owner1/repo1/pull/{n}",
        "user": {"login": "alice"},
        "head": {"ref": f"feature-{n}"},
        "base": {"ref": "main"},
    }


async def test_list_open_prs_paginates_until_short_page():
    session = FakeSession(
        list_pull_requests=[
            result([pr_item(1), pr_item(2)]),  # full page -> keep going
            result([pr_item(3)]),  # short page -> stop
        ]
    )
    prs = await client_for(session).list_open_prs()

    assert [p.number for p in prs] == [1, 2, 3]
    assert prs[0].author == "alice"
    assert prs[0].head_branch == "feature-1"
    assert prs[0].url.endswith("/pull/1")
    pages = [args["page"] for _, args in session.calls]
    assert pages == [1, 2]
    assert session.calls[0][1]["state"] == "open"
    assert session.calls[0][1]["owner"] == "owner1"
    assert session.calls[0][1]["repo"] == "repo1"


async def test_list_open_prs_empty_repo():
    session = FakeSession(list_pull_requests=[result([])])
    assert await client_for(session).list_open_prs() == []
    assert len(session.calls) == 1


async def test_get_pr_files_computes_deletions_and_paginates():
    session = FakeSession(
        pull_request_read=[
            result(
                [
                    {"filename": "a.py", "status": "modified", "additions": 5, "changes": 8},
                    {"filename": "b.py", "status": "added", "additions": 3, "changes": 3},
                ]
            ),
            result([{"filename": "c.py", "status": "removed", "additions": 0, "changes": 4}]),
        ]
    )
    files = await client_for(session).get_pr_files(42)

    assert [f.filename for f in files] == ["a.py", "b.py", "c.py"]
    assert (files[0].additions, files[0].deletions, files[0].changes) == (5, 3, 8)
    assert files[1].deletions == 0
    assert files[2].deletions == 4
    assert files[2].status == "removed"
    first_args = session.calls[0][1]
    assert first_args["method"] == "get_files"
    assert first_args["pullNumber"] == 42


async def test_list_branches_maps_fields_and_paginates():
    session = FakeSession(
        list_branches=[
            result(
                [
                    {"name": "main", "sha": "aaa", "protected": True},
                    {"name": "old-1", "sha": "bbb", "protected": False},
                ]
            ),
            result([{"name": "old-2", "sha": "ccc"}]),
        ]
    )
    branches = await client_for(session).list_branches()

    assert [b.name for b in branches] == ["main", "old-1", "old-2"]
    assert branches[0].protected is True
    assert branches[2].protected is False
    assert branches[1].sha == "bbb"


async def test_get_commit_date_parses_committer_date():
    session = FakeSession(
        get_commit=[result({"sha": "abc", "commit": {"committer": {"date": "2012-03-06T23:06:50Z"}}})]
    )
    date = await client_for(session).get_commit_date("abc")

    assert date == datetime(2012, 3, 6, 23, 6, 50, tzinfo=timezone.utc)
    assert session.calls[0][1]["sha"] == "abc"
    assert session.calls[0][1]["detail"] == "none"


async def test_get_commit_date_missing_field_raises():
    session = FakeSession(get_commit=[result({"sha": "abc", "commit": {}})])
    with pytest.raises(MCPError, match="no committer date"):
        await client_for(session).get_commit_date("abc")


async def test_error_result_raises_mcp_error():
    session = FakeSession(list_branches=[result("repository not found", is_error=True)])
    with pytest.raises(MCPError, match="list_branches failed: repository not found"):
        await client_for(session).list_branches()


async def test_non_json_result_raises_mcp_error():
    session = FakeSession(list_branches=[result("not json at all")])
    with pytest.raises(MCPError, match="non-JSON"):
        await client_for(session).list_branches()


async def test_non_list_page_raises_mcp_error():
    session = FakeSession(list_branches=[result({"message": "oops"})])
    with pytest.raises(MCPError, match="expected a list"):
        await client_for(session).list_branches()


async def test_call_without_connection_raises():
    client = GitHubMCPClient(make_settings())
    with pytest.raises(MCPError, match="not connected"):
        await client.list_branches()
