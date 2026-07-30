from pathlib import Path

from typer.testing import CliRunner

from arona.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_schema_export_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--output-directory", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "device-discovery.schema.json").is_file()
    assert (tmp_path / "optimize-request.schema.json").is_file()
    assert (tmp_path / "run-report.schema.json").is_file()
