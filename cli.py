"""Command line entry point: summarize, cleanup, all.

The other modules are imported lazily, so this CLI runs as soon as the pieces
it needs have landed. Expected interfaces (agree changes with the owners):

  summarize (Member 4, Kumar):
    risk.assess(pr, settings)                  -> RiskAssessment
    reviewers.suggest(pr, client, settings)    -> list[str]
    narrative.summarize(pr, risk, settings)    -> str
    report.write(summaries, settings)          -> None  (writes output/ files)

  cleanup (Member 5, Aneesh):
    cleanup.run(client, settings, execute: bool) -> list[BranchDecision]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import replace

from config import ConfigError, Settings, load_settings
from models import PullRequestSummary

log = logging.getLogger("pr-assistant")


def _missing(module: str, exc: ImportError) -> SystemExit:
    return SystemExit(f"Module '{module}' is not available yet: {exc}")


async def run_summarize(settings: Settings) -> list[PullRequestSummary]:
    try:
        import narrative
        import report
        import reviewers
        import risk
    except ImportError as exc:
        raise _missing("summarize pipeline", exc) from exc

    from mcp_client import GitHubMCPClient

    summaries: list[PullRequestSummary] = []
    async with GitHubMCPClient(settings) as client:
        prs = await client.list_open_prs()
        log.info("Found %d open pull request(s)", len(prs))
        for pr in prs:
            files = await client.get_pr_files(pr.number)
            pr = replace(pr, files=tuple(files))
            assessment = risk.assess(pr, settings)
            summaries.append(
                PullRequestSummary(
                    number=pr.number,
                    title=pr.title,
                    author=pr.author,
                    url=pr.url,
                    changed_files=pr.changed_files,
                    risk=assessment,
                    suggested_reviewers=await reviewers.suggest(pr, client, settings),
                    summary=narrative.summarize(pr, assessment, settings),
                )
            )
    report.write(summaries, settings)
    log.info("Wrote summaries to %s", settings.output_dir)
    return summaries


async def run_cleanup(settings: Settings, execute: bool) -> None:
    try:
        import cleanup
    except ImportError as exc:
        raise _missing("cleanup", exc) from exc

    from mcp_client import GitHubMCPClient

    async with GitHubMCPClient(settings) as client:
        await cleanup.run(client, settings, execute=execute)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-assistant", description="Automated PR Assistant")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summarize", help="summarize all open pull requests")

    for name, help_text in (
        ("cleanup", "delete merged branches older than the configured age"),
        ("all", "summarize, then clean up"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--execute",
            action="store_true",
            help="actually delete branches (default is a dry run)",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        settings = load_settings(require_bob_key=args.command in ("cleanup", "all"))
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "summarize":
        asyncio.run(run_summarize(settings))
    elif args.command == "cleanup":
        asyncio.run(run_cleanup(settings, args.execute))
    else:  # all
        asyncio.run(run_summarize(settings))
        asyncio.run(run_cleanup(settings, args.execute))
    return 0


if __name__ == "__main__":
    sys.exit(main())
