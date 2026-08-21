"""ONNX Runtime equivalence validation for exact graph rewrites."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]

from arona.contracts.v1 import (
    ArgMaxPostprocess,
    ArtifactKind,
    ArtifactRef,
    OutputError,
    ValidationResult,
    ValidationStatus,
)


def validate_externalized_argmax(
    baseline_model_path: Path,
    candidate_model_path: Path,
    postprocess: ArgMaxPostprocess,
    output_path: Path,
    *,
    sample_count: int = 10,
    seed: int = 260821,
) -> ValidationResult:
    """Compare baseline output with candidate output followed by the removed ArgMax."""

    artifact = ArtifactRef(
        kind=ArtifactKind.VALIDATION,
        path=str(output_path),
        media_type="application/json",
        description="ONNX Runtime terminal ArgMax equivalence result",
    )
    try:
        if sample_count < 1:
            raise ValueError("sample_count must be at least one")
        baseline_session = ort.InferenceSession(
            str(baseline_model_path), providers=["CPUExecutionProvider"]
        )
        candidate_session = ort.InferenceSession(
            str(candidate_model_path), providers=["CPUExecutionProvider"]
        )
        _check_session_contract(baseline_session, candidate_session)

        rng = np.random.default_rng(seed)
        absolute_errors: list[np.ndarray] = []
        mismatch_count = 0
        for _sample_index in range(sample_count):
            baseline_inputs = _random_inputs(baseline_session, rng)
            candidate_inputs = {
                value.name: baseline_inputs[value.name] for value in candidate_session.get_inputs()
            }
            baseline_output = baseline_session.run(None, baseline_inputs)[0]
            candidate_output = candidate_session.run(None, candidate_inputs)[0]
            if not np.isfinite(candidate_output).all():
                raise ValueError("candidate output contains NaN or Inf")

            reconstructed = _apply_argmax(candidate_output, postprocess)
            if not np.array_equal(baseline_output, reconstructed):
                mismatch_count += 1
            absolute_errors.append(
                np.abs(baseline_output.astype(np.float64) - reconstructed.astype(np.float64))
            )

        flattened_errors = np.concatenate([error.reshape(-1) for error in absolute_errors])
        status = ValidationStatus.PASSED if mismatch_count == 0 else ValidationStatus.FAILED
        reason = (
            "All reconstructed class indices match the baseline output."
            if mismatch_count == 0
            else f"{mismatch_count} of {sample_count} samples did not match."
        )
        result = ValidationResult(
            status=status,
            reference_runtime="onnxruntime:baseline",
            candidate_runtime="onnxruntime:candidate+postprocess",
            sample_count=sample_count,
            absolute_tolerance=0.0,
            relative_tolerance=0.0,
            outputs=[
                OutputError(
                    output_name=postprocess.output_name,
                    max_absolute_error=float(flattened_errors.max(initial=0.0)),
                    mean_absolute_error=float(flattened_errors.mean()),
                    max_relative_error=0.0 if mismatch_count == 0 else None,
                    cosine_similarity=1.0 if mismatch_count == 0 else None,
                )
            ],
            reason=reason,
            artifact=artifact,
        )
    except Exception as error:  # ONNX Runtime exposes several concrete exception classes.
        result = ValidationResult(
            status=ValidationStatus.ERROR,
            reference_runtime="onnxruntime:baseline",
            candidate_runtime="onnxruntime:candidate+postprocess",
            sample_count=0,
            absolute_tolerance=0.0,
            relative_tolerance=0.0,
            reason=str(error),
            artifact=artifact,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def _check_session_contract(
    baseline_session: ort.InferenceSession,
    candidate_session: ort.InferenceSession,
) -> None:
    baseline_inputs = baseline_session.get_inputs()
    candidate_inputs = candidate_session.get_inputs()
    if len(baseline_inputs) != len(candidate_inputs):
        raise ValueError("baseline and candidate input counts differ")
    if {value.name for value in baseline_inputs} != {value.name for value in candidate_inputs}:
        raise ValueError("baseline and candidate input names differ")
    if len(baseline_session.get_outputs()) != 1 or len(candidate_session.get_outputs()) != 1:
        raise ValueError("the MVP validator requires one output per model")


def _random_inputs(
    session: ort.InferenceSession,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    values: dict[str, np.ndarray] = {}
    for model_input in session.get_inputs():
        shape = tuple(
            _concrete_dimension(dimension, index)
            for index, dimension in enumerate(model_input.shape)
        )
        if model_input.type == "tensor(float)":
            values[model_input.name] = rng.uniform(0.0, 255.0, shape).astype(np.float32)
        elif model_input.type == "tensor(uint8)":
            values[model_input.name] = rng.integers(0, 256, shape, dtype=np.uint8)
        elif model_input.type == "tensor(int8)":
            values[model_input.name] = rng.integers(-128, 128, shape, dtype=np.int8)
        else:
            raise ValueError(f"unsupported validation input type: {model_input.type}")
    return values


def _concrete_dimension(dimension: int | str | None, index: int) -> int:
    if isinstance(dimension, int) and dimension > 0:
        return dimension
    if index == 0:
        return 1
    raise ValueError(f"dynamic non-batch input dimension is unsupported: {dimension}")


def _apply_argmax(values: np.ndarray, postprocess: ArgMaxPostprocess) -> np.ndarray:
    axis = postprocess.axis
    if postprocess.select_last_index:
        flipped = np.flip(values, axis=axis)
        selected = np.argmax(flipped, axis=axis)
        selected = values.shape[axis] - 1 - selected
    else:
        selected = np.argmax(values, axis=axis)
    if postprocess.keepdims:
        selected = np.expand_dims(selected, axis=axis)
    return np.asarray(selected, dtype=np.int64)
