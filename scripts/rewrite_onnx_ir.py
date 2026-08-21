"""Create and validate a lower-IR compatibility copy of an ONNX model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_model", type=Path)
    parser.add_argument("output_model", type=Path)
    parser.add_argument("--ir-version", type=int, default=9)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--seed", type=int, default=260821)
    args = parser.parse_args()

    model = onnx.load(args.input_model)
    source_ir = model.ir_version
    if source_ir <= args.ir_version:
        raise ValueError(f"Source IR {source_ir} is not newer than requested IR {args.ir_version}.")
    overloaded_nodes = [node.name or node.op_type for node in model.graph.node if node.overload]
    overloaded_functions = [function.name for function in model.functions if function.overload]
    if overloaded_nodes or overloaded_functions:
        raise ValueError("IR downgrade is unsafe because overload fields are in use.")

    model.ir_version = args.ir_version
    onnx.checker.check_model(model, full_check=True)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, args.output_model)

    rng = np.random.default_rng(args.seed)
    original = ort.InferenceSession(str(args.input_model), providers=["CPUExecutionProvider"])
    rewritten = ort.InferenceSession(str(args.output_model), providers=["CPUExecutionProvider"])
    if [(item.name, item.shape, item.type) for item in original.get_inputs()] != [
        (item.name, item.shape, item.type) for item in rewritten.get_inputs()
    ]:
        raise ValueError("Input contracts changed during IR rewrite.")

    maximum_absolute_error = 0.0
    for _ in range(args.samples):
        feeds = {
            item.name: rng.random(
                tuple(
                    dimension if isinstance(dimension, int) and dimension > 0 else 1
                    for dimension in item.shape
                ),
                dtype=np.float32,
            )
            for item in original.get_inputs()
        }
        expected = original.run(None, feeds)
        actual = rewritten.run(None, feeds)
        if len(expected) != len(actual):
            raise ValueError("Output count changed during IR rewrite.")
        for expected_output, actual_output in zip(expected, actual, strict=True):
            error = float(np.max(np.abs(expected_output - actual_output)))
            maximum_absolute_error = max(maximum_absolute_error, error)
            if not np.array_equal(expected_output, actual_output):
                raise ValueError(f"IR rewrite changed inference output; maximum error {error}.")

    evidence = {
        "source_model": str(args.input_model),
        "source_sha256": _sha256(args.input_model),
        "source_ir_version": source_ir,
        "rewritten_model": str(args.output_model),
        "rewritten_sha256": _sha256(args.output_model),
        "rewritten_ir_version": model.ir_version,
        "graph_node_count": len(model.graph.node),
        "samples": args.samples,
        "seed": args.seed,
        "outputs_bit_exact": True,
        "maximum_absolute_error": maximum_absolute_error,
    }
    evidence_path = args.output_model.with_suffix(".validation.json")
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
