"""Command-line entry point for ARONA."""

from pathlib import Path
from typing import Annotated

import typer

from arona import __version__
from arona.contracts.export import export_json_schemas

app = typer.Typer(
    name="arona",
    help="Optimize ONNX models for detected edge accelerators.",
    no_args_is_help=True,
)
schema_app = typer.Typer(help="Inspect and export backend/UI contracts.")
app.add_typer(schema_app, name="schema")


@app.command()
def version() -> None:
    """Print the installed ARONA version."""
    typer.echo(__version__)


@schema_app.command("export")
def export_schema(
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output-directory",
            "-o",
            help="Directory in which versioned JSON Schema files are written.",
        ),
    ] = Path("schemas/v0.1.0"),
) -> None:
    """Export versioned JSON Schemas used by backend and UI."""
    written_files = export_json_schemas(output_directory)
    for path in written_files:
        typer.echo(path.as_posix())
