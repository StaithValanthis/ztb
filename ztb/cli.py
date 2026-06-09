from __future__ import annotations

import sys

import click

from ztb import __version__


@click.group()
@click.version_option(version=__version__, prog_name="ztb")
def cli() -> None:
    pass


@cli.command()
def data() -> None:
    click.echo("data: not yet implemented")


@cli.command()
def backtest() -> None:
    click.echo("backtest: not yet implemented")


@cli.command()
def forwardtest() -> None:
    click.echo("forwardtest: not yet implemented")


@cli.command()
def validate() -> None:
    click.echo("validate: not yet implemented")


@cli.command()
def run() -> None:
    click.echo("run: not yet implemented")


@cli.command()
def report() -> None:
    click.echo("report: not yet implemented")


@cli.command()
def dashboard() -> None:
    click.echo("dashboard: not yet implemented")


@cli.command(name="list")
def _list() -> None:
    click.echo("list: not yet implemented")


def main() -> None:
    sys.exit(cli(auto_envvar_prefix="ZTB"))
