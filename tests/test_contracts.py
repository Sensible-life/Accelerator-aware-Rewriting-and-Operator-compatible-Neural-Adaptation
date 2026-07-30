import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arona.contracts.export import export_json_schemas
from arona.contracts.v1 import InputModelReference, OptimizeRequest, RunReport

ROOT = Path(__file__).parents[1]


def test_run_report_example_matches_contract() -> None:
    fixture_path = ROOT / "tests/fixtures/contracts/run-report.sample.json"
    report = RunReport.model_validate_json(fixture_path.read_text(encoding="utf-8"))

    assert report.status == "completed"
    assert report.decision is not None
    assert report.decision.selected == "optimized"


def test_optimize_request_has_safe_mvp_defaults() -> None:
    request = OptimizeRequest(model=InputModelReference(path="models/model.onnx"))

    assert request.optimization.enable_exact_rewrites is True
    assert request.optimization.enable_neural_adaptation is False
    assert request.optimization.require_measured_improvement is True


def test_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        OptimizeRequest.model_validate(
            {
                "model": {"path": "models/model.onnx"},
                "unexpected": "value",
            }
        )


def test_committed_json_schemas_are_current(tmp_path: Path) -> None:
    generated_files = export_json_schemas(tmp_path)
    committed_directory = ROOT / "schemas/v0.1.0"

    for generated_file in generated_files:
        committed_file = committed_directory / generated_file.name
        assert json.loads(generated_file.read_text(encoding="utf-8")) == json.loads(
            committed_file.read_text(encoding="utf-8")
        )
