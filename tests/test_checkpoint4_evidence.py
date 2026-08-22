import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "tests/fixtures/deployment/nucleo_checkpoint4_e2e/evidence.json"


def test_checkpoint4_evidence_is_complete_and_checksum_pinned() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["target"]["board"] == "NUCLEO-N657X0-Q"
    assert evidence["toolchain"]["stedgeai"].startswith("ST Edge AI Core v4.0.1")
    assert evidence["pre_deployment_backup"]["size_bytes"] == 64 * 1024 * 1024
    assert len(evidence["models"]) == 2

    for model in evidence["models"]:
        assert model["compiler"]["deployable"] == "feasible"
        assert model["compiler"]["selected"] == "baseline"
        assert model["firmware"]["programming_stages_succeeded"] == 3
        assert model["validation"]["inferences"] >= 5
        assert model["validation"]["successful_inferences"] == model["validation"]["inferences"]
        assert model["validation"]["fixed_input_fnv1a"].startswith("0x")
        for value in (
            model["model"]["sha256"],
            model["firmware"]["signed_application_sha256"],
            model["firmware"]["network_data_sha256"],
            model["validation"]["serial_log_sha256"],
        ):
            assert re.fullmatch(r"[0-9a-f]{64}", value)
