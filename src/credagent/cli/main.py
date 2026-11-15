"""`credagent` command-line entry point.

Sprint 0: every PRD command exists with its arguments and help text. Commands not
yet implemented say so plainly and exit with code 2 — they never imply success.
"""

from __future__ import annotations

import sys

import click

from credagent import __version__

NOT_IMPLEMENTED_EXIT = 2


def _not_yet(command: str, sprint: int) -> None:
    click.echo(
        f"`credagent {command}` is not implemented yet (planned for Sprint {sprint}). "
        "Nothing was run.",
        err=True,
    )
    sys.exit(NOT_IMPLEMENTED_EXIT)


def _validate_app(_ctx: click.Context, _param: click.Parameter, value: str) -> str:
    name = value.strip()
    if not name:
        raise click.BadParameter("give the app name, e.g. credagent get \"GitHub\"")
    if len(name) > 100:
        raise click.BadParameter("app name is too long (max 100 characters)")
    if any(ch in name for ch in "\n\r\t"):
        raise click.BadParameter("app name must be a single line")
    return name


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="credagent")
def cli() -> None:
    """CredAgent: get working developer credentials for an app, with a live test.

    Runs locally. Opens a visible browser, pauses for steps only you should do
    (sign-in, codes, CAPTCHA, terms, payment), saves progress after every step,
    and stores credentials outside the repo.
    """


@cli.command()
@click.argument("app", callback=_validate_app)
def get(app: str) -> None:
    """Start a new run to obtain credentials for APP (e.g. "GitHub")."""
    _not_yet("get", 2)


@cli.command()
@click.argument("run_id")
def resume(run_id: str) -> None:
    """Resume RUN_ID from its last checkpoint (re-checks the page before acting)."""
    _not_yet("resume", 5)


@cli.command()
@click.argument("run_id", required=False)
def status(run_id: str | None) -> None:
    """Show status, current step, pending handoff and next action (no secrets)."""
    _not_yet("status", 2)


@cli.command()
def runs() -> None:
    """List local runs and their outcomes."""
    _not_yet("runs", 2)


@cli.command()
@click.argument("run_id")
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default="md",
              show_default=True, help="Report format.")
def report(run_id: str, fmt: str) -> None:
    """Show the Markdown or JSON report for RUN_ID."""
    _not_yet("report", 2)


@cli.command()
@click.argument("run_id")
def verify(run_id: str) -> None:
    """Run (or re-run) the live credential test for RUN_ID without showing the secret."""
    _not_yet("verify", 5)


@cli.command()
@click.argument("run_id")
@click.option("--reveal", is_flag=True,
              help="Intentionally reveal the stored secret (asks for confirmation).")
def secret(run_id: str, reveal: bool) -> None:
    """Show where RUN_ID's credential is stored (masked by default)."""
    _not_yet("secret", 5)


if __name__ == "__main__":
    cli()
