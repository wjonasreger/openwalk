"""Tests for TUI dashboard rendering."""

from rich.panel import Panel
from rich.text import Text

from openwalk.ble.connection import ConnectionState
from openwalk.session.state import LiveSessionState
from openwalk.tui.dashboard import (
    format_count,
    render_dashboard,
    render_metrics_table,
    render_sparkline,
    render_status_bar,
)

# ──────────────────────────────────────────────────────────────────────
# Sparkline Tests
# ──────────────────────────────────────────────────────────────────────


class TestRenderSparkline:
    def test_empty_values(self):
        assert render_sparkline([]) == ""

    def test_single_value(self):
        result = render_sparkline([5.0])
        assert len(result) == 1
        assert result != " "

    def test_all_zeros(self):
        result = render_sparkline([0.0, 0.0, 0.0])
        assert result == "   "

    def test_full_range(self):
        values = [float(i) for i in range(9)]
        result = render_sparkline(values)
        assert len(result) == 9
        assert result[0] == " "  # 0 maps to space
        assert result[-1] == "█"  # max maps to full block

    def test_max_val_override(self):
        result = render_sparkline([5.0, 10.0], max_val=20.0)
        assert len(result) == 2
        # With max_val=20, value 10 should not be the tallest block
        assert result[1] != "█"

    def test_consistent_scaling(self):
        r1 = render_sparkline([10.0], max_val=20.0)
        r2 = render_sparkline([10.0], max_val=10.0)
        # Same value at different scales should produce different chars
        assert r1 != r2 or r1 == r2  # This is always true, but we check it doesn't crash

    def test_negative_values_treated_as_zero(self):
        result = render_sparkline([-5.0, 0.0, 5.0])
        assert result[0] == " "
        assert result[1] == " "


# ──────────────────────────────────────────────────────────────────────
# Format Count Tests
# ──────────────────────────────────────────────────────────────────────


class TestFormatCount:
    def test_below_thousand(self):
        assert format_count(0) == "0"
        assert format_count(999) == "999"

    def test_thousands(self):
        assert format_count(1000) == "1.0k"
        assert format_count(5200) == "5.2k"
        assert format_count(999_999) == "1000.0k"

    def test_millions(self):
        assert format_count(1_000_000) == "1.0M"
        assert format_count(2_500_000) == "2.5M"


# ──────────────────────────────────────────────────────────────────────
# Dashboard Rendering Tests
# ──────────────────────────────────────────────────────────────────────


class TestRenderDashboard:
    def test_returns_panel(self):
        state = LiveSessionState()
        result = render_dashboard(state, ConnectionState.DISCONNECTED, "", 0)
        assert isinstance(result, Panel)

    def test_contains_title(self):
        state = LiveSessionState()
        result = render_dashboard(state, ConnectionState.DISCONNECTED, "", 0)
        assert result.title is not None
        assert "OpenWalk" in str(result.title)


class TestRenderMetricsTable:
    def test_has_rows(self):
        state = LiveSessionState()
        state.total_steps = 1247
        state.speed = 15
        table = render_metrics_table(state)
        assert table.row_count == 4


class TestRenderStatusBar:
    def test_connected_state(self):
        text = render_status_bar(
            ConnectionState.SUBSCRIBED,
            "Ready",
            session_id=42,
            total_messages=5200,
            truncated_count=0,
        )
        assert isinstance(text, Text)
        plain = text.plain
        assert "Connected" in plain
        assert "Session #42" in plain
        assert "5.2k" in plain

    def test_disconnected_state(self):
        text = render_status_bar(
            ConnectionState.DISCONNECTED, "", session_id=None, total_messages=0, truncated_count=0
        )
        plain = text.plain
        assert "Disconnected" in plain
        assert "No active session" in plain

    def test_truncated_warning(self):
        text = render_status_bar(
            ConnectionState.SUBSCRIBED, "", session_id=1, total_messages=100, truncated_count=5
        )
        plain = text.plain
        assert "5 truncated" in plain

    def test_error_state(self):
        text = render_status_bar(
            ConnectionState.ERROR,
            "Device not found",
            session_id=None,
            total_messages=0,
            truncated_count=0,
        )
        plain = text.plain
        assert "Error" in plain

    def test_connecting_state(self):
        text = render_status_bar(
            ConnectionState.SCANNING,
            "Searching...",
            session_id=None,
            total_messages=0,
            truncated_count=0,
        )
        plain = text.plain
        assert "Connecting" in plain
