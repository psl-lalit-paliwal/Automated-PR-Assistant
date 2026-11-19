# GitHub remote MCP server: verified findings

Endpoint: `https://api.githubcopilot.com/mcp/` (HTTP 200 on `initialize`, session via `Mcp-Session-Id` header).
Auth: `Authorization: Bearer <GITHUB_TOKEN>`. Server exposes 46 tools.

## Tools we use

| Need | Tool | Key arguments |
|---|---|---|
| Open PRs | `list_pull_requests` | `owner, repo, state=open, page, perPage` |
| Closed/merged PRs (branch matching) | `list_pull_requests` | `state=closed` (check `merged_at` in each item) |
| PR files | `pull_request_read` | `method=get_files, owner, repo, pullNumber, page, perPage` |
| Branches | `list_branches` | `owner, repo, page, perPage` |
| Commit date | `get_commit` | `owner, repo, sha, detail=none` |
| Recent authors of a file | `list_commits` | `owner, repo, path, perPage` |
| CODEOWNERS | `get_file_contents` | `owner, repo, path=.github/CODEOWNERS` (or `CODEOWNERS`) |

## Branch delete: NOT available

There is no `delete_branch` tool. The only delete-like tool is `delete_file`, which removes a file, not a branch.
Neither `git push --delete` nor the REST call `DELETE /repos/{o}/{r}/git/refs/heads/{branch}` is exposed through MCP.

Consequences for Aneesh (Member 5, `cleanup.py`):
- Bob cannot delete a branch through this MCP server.
- Options: (a) Bob Shell runs the delete itself through its shell tool, for example
  `git push origin --delete <branch>` or `gh api -X DELETE repos/<o>/<r>/git/refs/heads/<branch>`;
  (b) call the GitHub REST API directly from Python.
- Verification after delete can still use `list_branches` through MCP.

## Bob Shell 2.1.0 results

- The GitHub MCP server connects from .bob/mcp.json and Bob loads 46 tools.
- Header expansion uses ${env:NAME}. A bare ${NAME} is sent as literal text.
- 	ype: streamable-http is optional. The result is the same with and without it.
- ob run needs BOB_API_KEY.

