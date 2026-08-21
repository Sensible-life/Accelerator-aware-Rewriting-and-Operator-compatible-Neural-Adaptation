import os
from pathlib import Path

import pytest

from arona.deployment.commands import SubprocessCommandRunner
from arona.deployment.stm32n6 import resolve_programmer

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.getenv("ARONA_RUN_HARDWARE") != "1",
        reason="set ARONA_RUN_HARDWARE=1 to run read-only NUCLEO probes",
    ),
]


def test_connected_board_is_nucleo_n657x0_q() -> None:
    programmer = resolve_programmer()
    assert programmer is not None

    outcome = SubprocessCommandRunner().run(
        [str(programmer), "-c", "port=SWD", "mode=HOTPLUG"],
        working_directory=Path.cwd(),
        timeout_seconds=30,
    )

    assert outcome.exit_code == 0
    assert "Board       : NUCLEO-N657X0-Q" in outcome.stdout
