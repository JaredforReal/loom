"""Loom CLI entry point."""

from __future__ import annotations

import click


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
@click.argument("kind")
@click.option("--repo", help="GitHub repo (owner/repo)")
@click.option("--url", help="Feed URL (RSS)")
@click.option("--credentials", help="Path to credentials file")
def source_add(kind: str, repo: str | None, url: str | None, credentials: str | None) -> None:
    """Add a new source subscription."""
    click.echo(f"Adding {kind} source...")


@source.command("list")
def source_list() -> None:
    """List configured sources."""
    click.echo("Configured sources: (none)")


@cli.command()
def ui() -> None:
    """Open the Loom web UI in a browser."""
    click.echo("Opening http://localhost:8732 ...")
    # TODO: webbrowser.open("http://localhost:8732")


if __name__ == "__main__":
    cli()
