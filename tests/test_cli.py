from pathlib import Path

import onnx
from onnx import TensorProto, helper
from typer.testing import CliRunner

from arona.cli import app

runner = CliRunner()
ROOT = Path(__file__).parents[1]


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_schema_export_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--output-directory", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "device-discovery.schema.json").is_file()
    assert (tmp_path / "device-probe.schema.json").is_file()
    assert (tmp_path / "optimize-request.schema.json").is_file()
    assert (tmp_path / "run-report.schema.json").is_file()


def test_analyze_command_writes_json_and_markdown_report(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_identity_model(model_path)
    compiler_log = ROOT / "tests/fixtures/backends/stedgeai/conmamba_fallback/compiler.log"

    result = runner.invoke(
        app,
        [
            "analyze",
            str(model_path),
            "--compiler-log",
            str(compiler_log),
            "--output-directory",
            str(tmp_path / "outputs"),
        ],
    )

    assert result.exit_code == 0
    assert "software=1530" in result.stdout
    assert "deployable: infeasible" in result.stdout
    run_dirs = list((tmp_path / "outputs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "original-analysis.json").is_file()
    assert (run_dirs[0] / "report.md").is_file()


def _write_identity_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])
    graph = helper.make_graph(
        nodes=[helper.make_node("Identity", ["input"], ["output"], name="identity_0")],
        name="identity",
        inputs=[input_info],
        outputs=[output_info],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    onnx.save(model, path)
