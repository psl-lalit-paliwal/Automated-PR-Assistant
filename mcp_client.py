"""Async client for the remote GitHub MCP server.

Wraps the four read operations the pipeline needs. Tool names and argument
shapes were verified against https://api.githubcopilot.com/mcp/
(see docs/mcp_findings.md). The server returns JSON text in content[0].text.

Branch deletion is NOT available through this server.
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from config import Settings
from models import Branch, ChangedFile, PullRequest

log = logging.getLogger(__name__)

MAX_PAGES = 100  # safety stop against an endless pagination loop


class MCPError(RuntimeError):
    """The MCP server returned an error result or an unparseable payload."""


def _parse_json(result: Any, tool: str) -> Any:
    text = result.content[0].text if result.content else ""
    if result.is_error:
        raise MCPError(f"{tool} failed: {text[:300]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPError(f"{tool} returned non-JSON content: {text[:200]!r}") from exc


class GitHubMCPClient:
    """Use as `async with GitHubMCPClient(settings) as client:`.

    Tests can pass `session=` (any object with an async `call_tool(name, args)`)
    to skip the network connection.
    """

    def __init__(self, settings: Settings, session: Any | None = None) -> None:
        self._settings = settings
        self._session = session
        self._stack: AsyncExitStack | None = None
        self._owner = settings.github_owner
        self._repo = settings.github_repo

    async def __aenter__(self) -> GitHubMCPClient:
        if self._session is None:
            self._stack = AsyncExitStack()
            http = create_mcp_http_client(
                headers={"Authorization": f"Bearer {self._settings.github_token}"}
            )
            streams = await self._stack.enter_async_context(
                streamable_http_client(self._settings.mcp_url, http_client=http)
            )
            session = await self._stack.enter_async_context(ClientSession(*streams[:2]))
            await session.initialize()
            self._session = session
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    async def _call(self, tool: str, **args: Any) -> Any:
        if self._session is None:
            raise MCPError("client is not connected; use 'async with'")
        log.debug("MCP call %s %s", tool, args)
        result = await self._session.call_tool(
            tool, {"owner": self._owner, "repo": self._repo, **args}
        )
        return _parse_json(result, tool)

    async def _paginate(self, tool: str, **args: Any) -> list[Any]:
        """Collect every page. Stops on a short or empty page."""
        per_page = self._settings.per_page
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            batch = await self._call(tool, page=page, perPage=per_page, **args)
            if not isinstance(batch, list):
                raise MCPError(f"{tool} page {page}: expected a list, got {type(batch).__name__}")
            items.extend(batch)
            if len(batch) < per_page:
                return items
        raise MCPError(f"{tool}: more than {MAX_PAGES} pages, giving up")

    async def list_open_prs(self) -> list[PullRequest]:
        raw = await self._paginate("list_pull_requests", state="open")
        return [
            PullRequest(
                number=item["number"],
                title=item.get("title", ""),
                author=(item.get("user") or {}).get("login", ""),
                url=item.get("html_url", ""),
                head_branch=(item.get("head") or {}).get("ref", ""),
                base_branch=(item.get("base") or {}).get("ref", ""),
            )
            for item in raw
        ]

    async def get_pr_files(self, pr_number: int) -> list[ChangedFile]:
        raw = await self._paginate("pull_request_read", method="get_files", pullNumber=pr_number)
        files = []
        for item in raw:
            additions = int(item.get("additions", 0))
            # The API gives additions and changes but no deletions field.
            deletions = max(int(item.get("changes", additions)) - additions, 0)
            files.append(
                ChangedFile(
                    filename=item["filename"],
                    additions=additions,
                    deletions=deletions,
                    status=item.get("status", "modified"),
                )
            )
        return files

    async def list_branches(self) -> list[Branch]:
        raw = await self._paginate("list_branches")
        return [
            Branch(
                name=item["name"],
                sha=item.get("sha", ""),
                protected=bool(item.get("protected", False)),
            )
            for item in raw
        ]

    async def get_commit_date(self, sha: str) -> datetime:
        data = await self._call("get_commit", sha=sha, detail="none")
        try:
            stamp = data["commit"]["committer"]["date"]
        except (KeyError, TypeError) as exc:
            raise MCPError(f"get_commit {sha}: no committer date in response") from exc
        return datetime.fromisoformat(stamp)
