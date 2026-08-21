from pathlib import Path

import onnx
from onnx import TensorProto, helper

from arona.backends.stedgeai import StEdgeAiAdapter
from arona.contracts.v1 import RewriteStatus, ValidationStatus
from arona.pipeline.optimize import optimize_model

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/backends/stedgeai"


class RecordingStEdgeAiAdapter(StEdgeAiAdapter):
    def __init__(self, logs: list[Path]) -> None:
        self.logs = logs
        self.compiled_models: list[str] = []

    def compile(self, model: Path, output_directory: Path, timeout_seconds: int = 120) -> Path:
        self.compiled_models.append(model.name)
        return self.logs[len(self.compiled_models) - 1]


def test_pipeline_selects_validated_compiler_improvement(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_terminal_argmax_model(model_path)

    report = optimize_model(
        model_path,
        tmp_path / "outputs",
        baseline_compiler_log=FIXTURES / "conmamba_fallback/compiler.log",
        candidate_compiler_log=FIXTURES / "conmamba_xip_101/compiler.log",
    )

    assert report.decision is not None
    assert report.decision.selected == "optimized"
    assert report.decision.accepted is True
    assert report.optimized is not None
    assert report.rewrites[0].status == RewriteStatus.APPLIED
    assert report.rewrites[0].validation is not None
    assert report.rewrites[0].validation.status == ValidationStatus.PASSED


def test_pipeline_live_compile_calls_baseline_before_candidate(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_terminal_argmax_model(model_path)
    adapter = RecordingStEdgeAiAdapter(
        [
            FIXTURES / "conmamba_fallback/compiler.log",
            FIXTURES / "conmamba_xip_101/compiler.log",
        ]
    )

    report = optimize_model(model_path, tmp_path / "outputs", adapter=adapter)

    assert adapter.compiled_models == ["model.onnx", "optimized-model.onnx"]
    assert report.decision is not None
    assert report.decision.selected == "optimized"


def test_pipeline_rolls_back_when_compiler_has_no_improvement(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_terminal_argmax_model(model_path)
    log = FIXTURES / "conmamba_xip_101/compiler.log"

    report = optimize_model(
        model_path,
        tmp_path / "outputs",
        baseline_compiler_log=log,
        candidate_compiler_log=log,
    )

    assert report.decision is not None
    assert report.decision.selected == "baseline"
    assert report.rewrites[0].status == RewriteStatus.ROLLED_BACK
    assert "no measured compiler improvement" in report.decision.reasons[0]


def test_pipeline_rolls_back_when_candidate_compile_fails(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_terminal_argmax_model(model_path)

    report = optimize_model(
        model_path,
        tmp_path / "outputs",
        baseline_compiler_log=FIXTURES / "conmamba_xip_101/compiler.log",
        candidate_compiler_log=FIXTURES / "conmamba_fallback/compiler.log",
    )

    assert report.decision is not None
    assert report.decision.selected == "baseline"
    assert report.decision.accepted is True
    assert report.rewrites[0].status == RewriteStatus.ROLLED_BACK
    assert "compile" in report.decision.reasons[0].lower()


def _write_terminal_argmax_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("class_index", TensorProto.INT64, [1])
    graph = helper.make_graph(
        [
            helper.make_node("Identity", ["input"], ["scores"], name="identity_0"),
            helper.make_node(
                "ArgMax",
                ["scores"],
                ["class_index"],
                name="argmax_0",
                axis=1,
                keepdims=0,
            ),
        ],
        "terminal_argmax",
        [input_info],
        [output_info],
        value_info=[helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 3])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.save(model, path)
