"""CLI entry point for OpenWalk."""

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
    click.echo("OpenWalk starting... (not yet implemented)")
    if debug:
        click.echo("Debug mode enabled")


if __name__ == "__main__":
    cli()
