"""Loom CLI entry point."""

from __future__ import annotations

import click

from loom.config import load_config, save_config


@click.group()
@click.version_option()
def cli() -> None:
    """Loom — Mailbox and agent orchestration for Claude Code."""


@cli.command()
def daemon() -> None:
    """Start the Loom daemon (mailbox + dispatcher + web UI)."""
    click.echo("Starting Loom daemon...")
    # TODO: Initialize store, bus, mailbox, adaptors, dispatcher, web UI
    # TODO: asyncio.run(main_loop())


@cli.command()
def status() -> None:
    """Show daemon status, active sessions, and queue backlog."""
    click.echo("Loom status: not yet implemented")


@cli.group()
def source() -> None:
    """Manage external sources."""


@source.command("add")
@click.argument("kind", type=click.Choice(["github", "rss", "gmail", "anet"]))
@click.option("--repo", help="GitHub repo (owner/repo)", multiple=True)
@click.option("--events", help="GitHub events to track (issues,pull_requests)", default="issues,pull_requests")
@click.option("--interval", help="Poll interval in seconds", default=120, type=int)
@click.option("--state", help="Issue/PR state filter (open, closed, all)", default="all")
@click.option("--url", help="Feed URL (RSS)")
@click.option("--credentials", help="Path to credentials file")
@click.option("--token", help="GitHub personal access token (or set GITHUB_TOKEN env)")
def source_add(
    kind: str,
    repo: tuple[str, ...],
    events: str,
    interval: int,
    state: str,
    url: str | None,
    credentials: str | None,
    token: str | None,
) -> None:
    """Add a new source subscription."""
    config = load_config()

    if kind == "github":
        if not repo:
            click.echo("Error: --repo is required for GitHub sources (e.g. --repo owner/repo)")
            raise SystemExit(1)

        event_list = [e.strip() for e in events.split(",")]
        for r in repo:
            parts = r.split("/")
            if len(parts) != 2:
                click.echo(f"Error: Invalid repo format '{r}' — expected 'owner/repo'")
                raise SystemExit(1)

            source_entry = {
                "kind": "github",
                "owner": parts[0],
                "repo": parts[1],
                "poll_interval": interval,
                "events": event_list,
                "state": state,
            }
            config.sources.append(source_entry)
            click.echo(f"  Added: {r} (events={event_list}, interval={interval}s, state={state})")

        save_config(config)
        click.echo(f"\nGitHub source(s) saved to config. Token: {'provided' if token else 'GITHUB_TOKEN env'}")
        click.echo("Run `loom daemon` to start monitoring.")

    elif kind == "gmail":
        source_entry = {
            "kind": "gmail",
            "client_secrets": credentials or "~/.loom/credentials/gmail-client-secrets.json",
        }
        config.sources.append(source_entry)
        save_config(config)
        click.echo(f"Gmail source saved to config.")
        click.echo("Run `loom daemon` to start monitoring.")

    elif kind == "rss":
        if not url:
            click.echo("Error: --url is required for RSS sources")
            raise SystemExit(1)
        source_entry = {"kind": "rss", "url": url}
        config.sources.append(source_entry)
        save_config(config)
        click.echo(f"RSS source saved: {url}")

    elif kind == "anet":
        source_entry = {"kind": "anet"}
        config.sources.append(source_entry)
        save_config(config)
        click.echo("Anet source saved to config.")


@source.command("list")
def source_list() -> None:
    """List configured sources."""
    config = load_config()
    if not config.sources:
        click.echo("No sources configured. Use `loom source add <kind>` to add one.")
        return

    for i, s in enumerate(config.sources, 1):
        kind = s.get("kind", "unknown")
        if kind == "github":
            label = f"{s.get('owner', '?')}/{s.get('repo', '?')}"
        elif kind == "gmail":
            label = f"Gmail ({s.get('query', 'is:unread')})"
        elif kind == "rss":
            label = s.get("url", "unknown")
        else:
            label = str(s)
        click.echo(f"  {i}. [{kind}] {label}")


@cli.command()
def ui() -> None:
    """Open the Loom web UI in a browser."""
    click.echo("Opening http://localhost:8732 ...")
    # TODO: webbrowser.open("http://localhost:8732")


if __name__ == "__main__":
    cli()
