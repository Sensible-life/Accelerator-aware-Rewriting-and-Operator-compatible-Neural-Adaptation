"""Command-line entry point for ARONA."""

from pathlib import Path
from typing import Annotated

import typer

from arona import __version__
from arona.contracts.export import export_json_schemas
from arona.pipeline.analyze import analyze_model, discover_stedgeai
from arona.reporting.markdown import render_markdown_report
from arona.reporting.terminal import render_discovery, render_run_report

# denote arona as an app
app = typer.Typer(
    name="arona",
    help="Optimize ONNX models for detected edge accelerators.",
    no_args_is_help=True,
)

# create schema subcommand(ex: arona schema export)
schema_app = typer.Typer(help="Inspect and export backend/pipeline/CLI contracts.")
app.add_typer(schema_app, name="schema")


@app.command()
def version() -> None:
    """Print the installed ARONA version."""
    typer.echo(__version__)


@app.command()
def discover() -> None:
    """Probe the local ST Edge AI target environment."""

    discovery = discover_stedgeai()
    typer.echo(render_discovery(discovery))


@app.command()
def analyze(
    model: Annotated[
        Path,
        typer.Argument(help="Path to the ONNX model to analyze."),
    ],
    compiler_log: Annotated[
        Path,
        typer.Option(
            "--compiler-log",
            help="Captured stedgeai compiler log to parse as the baseline evidence.",
        ),
    ],
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output-directory",
            "-o",
            help="Directory in which the run report and Markdown report are written.",
        ),
    ] = Path("outputs"),
) -> None:
    """Analyze an ONNX model and captured baseline compiler evidence."""

    report = analyze_model(model, compiler_log=compiler_log, output_directory=output_directory)
    run_directory = output_directory / report.run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "original-analysis.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_directory / "report.md").write_text(
        render_markdown_report(report),
        encoding="utf-8",
    )
    typer.echo(render_run_report(report))
    typer.echo(f"\nArtifacts written to {run_directory.as_posix()}")


@app.command()
def optimize(
    model: Annotated[
        Path,
        typer.Argument(help="Path to the ONNX model to optimize."),
    ],
    compiler_log: Annotated[
        Path | None,
        typer.Option(
            "--compiler-log",
            help="Captured stedgeai compiler log. Required until live compile is enabled.",
        ),
    ] = None,
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o"),
    ] = Path("outputs"),
) -> None:
    """Run the MVP optimization pipeline.

    Sprint 1/2 currently performs baseline analysis and deployability diagnosis. Exact
    rewrites are added in the next pipeline stage, so this command intentionally reports
    a baseline decision when no safe rewrite candidate exists yet.
    """

    if compiler_log is None:
        raise typer.BadParameter(
            "--compiler-log is required until live stedgeai compile is enabled"
        )
    report = analyze_model(model, compiler_log=compiler_log, output_directory=output_directory)
    run_directory = output_directory / report.run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "original-analysis.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_directory / "report.md").write_text(
        render_markdown_report(report),
        encoding="utf-8",
    )
    typer.echo(render_run_report(report))
    typer.echo("\nNo exact rewrite candidate was applied in the Sprint 1/2 baseline pipeline.")
    typer.echo(f"Artifacts written to {run_directory.as_posix()}")


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
    """Export versioned JSON Schemas used by backend, pipeline, and CLI."""
    written_files = export_json_schemas(output_directory)
    for path in written_files:
        typer.echo(path.as_posix())
