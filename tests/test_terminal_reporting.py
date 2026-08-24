from io import StringIO

from arona.reporting.terminal import (
    ARONA_BLUE,
    ARONA_OK,
    ARONA_PINK,
    RESET,
    render_action_result,
    render_banner,
    render_heading,
    render_notice,
    render_pipeline_overview,
    render_pipeline_tracker,
    render_progress_step,
    render_status_icon,
    terminal_color_enabled,
    write_terminal,
)


class _TerminalStream(StringIO):
    def isatty(self) -> bool:
        return True


def test_terminal_color_is_enabled_for_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("ARONA_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)

    assert terminal_color_enabled(_TerminalStream()) is True


def test_arona_color_overrides_no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("ARONA_COLOR", "1")

    assert terminal_color_enabled(_TerminalStream()) is True
    assert render_status_icon("succeeded") == f"{ARONA_OK}✓{RESET}"


def test_arona_color_forces_ansi_in_non_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("ARONA_COLOR", "1")
    monkeypatch.setenv("ARONA_UNICODE", "1")

    assert terminal_color_enabled(StringIO()) is True
    assert render_heading("Model") == f"{ARONA_BLUE}Model{RESET}"
    assert render_status_icon("succeeded") == f"{ARONA_OK}✓{RESET}"
    banner = "\n".join(render_banner())
    assert f"{ARONA_PINK}A R O N A{RESET}" in banner
    assert f"{ARONA_PINK}Neural-ART / NPU{RESET}" in banner


def test_scene_art_uses_foreground_color_without_background_highlights(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("ARONA_COLOR", "1")
    monkeypatch.setenv("ARONA_UNICODE", "1")

    banner = "\n".join(render_banner())

    assert "\x1b[48;" not in banner
    assert f"{ARONA_BLUE}" in banner
    assert f"{ARONA_PINK}" in banner


def test_terminal_writer_preserves_truecolor_ansi() -> None:
    output = StringIO()
    message = f"{ARONA_BLUE}Model{RESET}"

    write_terminal(message, output)

    assert output.getvalue() == f"{message}\n"


def test_no_color_keeps_unicode_banner(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("ARONA_COLOR", raising=False)
    monkeypatch.setenv("ARONA_UNICODE", "1")

    banner = "\n".join(render_banner())

    assert "A R O N A" in banner
    assert "◇" in banner
    assert "\x1b[" not in banner


def test_banner_keeps_welcome_divider_and_aligned_model_input(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("ARONA_UNICODE", "1")

    lines = render_banner()
    model_line = lines[3]
    diamond_line = lines[4]
    vertical_line = lines[5]
    arrow_line = lines[6]
    model_center = model_line.index("ONNX MODEL") + (len("ONNX MODEL") - 1) / 2

    assert lines[0] == "Welcome to ARONA"
    assert set(lines[1]) == {"."}
    assert set(lines[11]) == {"."}
    assert abs(model_center - diamond_line.index("◇")) <= 0.5
    assert diamond_line.index("◇") == vertical_line.index("│") == arrow_line.index("╰")


def test_notice_wraps_long_content_to_terminal_width(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("ARONA_COLOR", raising=False)
    monkeypatch.setenv("ARONA_UNICODE", "1")

    notice = render_notice("Artifacts written", ["C:/" + "very-long-directory/" * 8])

    assert notice[0].startswith("╭─ ✓ Artifacts written")
    assert notice[-1].startswith("╰")
    assert max(len(line) for line in notice) <= 80


def test_progress_and_action_result_share_cli_ux(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("ARONA_COLOR", raising=False)
    monkeypatch.setenv("ARONA_UNICODE", "1")

    step = render_progress_step(2, 4, "Build and link", "succeeded")
    result = render_action_result("Deployment / Configure", "Configured", "app/main.c")

    assert step == "  ✓ 2/4 Build and link"
    assert "ARONA  Deployment / Configure" in result
    assert "✓ Configured" in result


def test_pipeline_tracker_distinguishes_running_and_pending(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("ARONA_UNICODE", "1")

    tracker = render_pipeline_tracker(
        [("Inspect", "succeeded"), ("Analyze", "running"), ("Optimize", "pending")]
    )

    assert tracker == [
        "Deployment pipeline",
        "  ✓ Inspect",
        "  │",
        "  ◆ Analyze  Running",
        "  │",
        "  ○ Optimize",
    ]

    overview = render_pipeline_overview(
        [("Inspect", "succeeded"), ("Analyze", "running"), ("Optimize", "pending")]
    )
    assert overview == "Workflow  ✓ Inspect ─ ◆ Analyze ─ ○ Optimize"
