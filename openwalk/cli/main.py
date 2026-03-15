"""CLI entry point for OpenWalk."""

import asyncio

import click


@click.group()
@click.version_option()
def cli() -> None:
    """OpenWalk - macOS terminal app for the InMovement Unsit treadmill."""
    pass


@cli.command()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def run(debug: bool) -> None:
    """Start OpenWalk and connect to treadmill."""
    from openwalk.tui.app import run_app

    asyncio.run(run_app(debug=debug))


if __name__ == "__main__":
    cli()
