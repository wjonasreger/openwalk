"""Tests for CLI commands: history, export, and config."""

import json

import pytest

from openwalk.config import (
    DEFAULT_CONFIG,
    config_to_profile,
    format_config,
    load_config,
    save_config,
)
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager
from openwalk.storage.sessions import SessionManager

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    async with Database(":memory:") as db:
        yield db


@pytest.fixture
async def session_mgr(db):
    return SessionManager(db)


@pytest.fixture
async def sample_mgr(db):
    return SampleManager(db)


# ──────────────────────────────────────────────────────────────────────
# Config Tests
# ──────────────────────────────────────────────────────────────────────


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.toml")
        assert config["user"]["weight_lbs"] == 275.0
        assert config["user"]["gender"] == "male"

    def test_loads_from_file(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[user]\nweight_lbs = 180.0\ngender = "female"\n')
        config = load_config(path)
        assert config["user"]["weight_lbs"] == 180.0
        assert config["user"]["gender"] == "female"
        # Defaults for unset values
        assert config["user"]["height_inches"] == 67.0

    def test_handles_invalid_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("not valid toml {{{{")
        config = load_config(path)
        # Should fall back to defaults
        assert config["user"]["weight_lbs"] == 275.0


class TestSaveConfig:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(DEFAULT_CONFIG, path)
        assert path.exists()
        content = path.read_text()
        assert "weight_lbs" in content
        assert "gender" in content

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "config.toml"
        save_config(DEFAULT_CONFIG, path)
        assert path.exists()

    def test_roundtrip(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(DEFAULT_CONFIG, path)
        loaded = load_config(path)
        assert loaded["user"]["weight_lbs"] == DEFAULT_CONFIG["user"]["weight_lbs"]
        assert loaded["user"]["gender"] == DEFAULT_CONFIG["user"]["gender"]


class TestConfigToProfile:
    def test_default_config(self):
        profile = config_to_profile(DEFAULT_CONFIG)
        assert profile.weight_lbs == 275.0
        assert profile.height_inches == 67.0
        assert profile.age_years == 29
        assert profile.gender == "male"

    def test_custom_config(self):
        config = {
            "user": {
                "weight_lbs": 160.0,
                "height_inches": 72.0,
                "age_years": 35,
                "gender": "female",
            }
        }
        profile = config_to_profile(config)
        assert profile.weight_lbs == 160.0
        assert profile.gender == "female"

    def test_missing_user_section(self):
        profile = config_to_profile({})
        # Should use defaults
        assert profile.weight_lbs == 275.0


class TestFormatConfig:
    def test_basic_output(self):
        output = format_config(DEFAULT_CONFIG)
        assert "[user]" in output
        assert "weight_lbs" in output


# ──────────────────────────────────────────────────────────────────────
# History Query Tests
# ──────────────────────────────────────────────────────────────────────


class TestHistoryQuery:
    async def test_no_sessions(self, session_mgr):
        sessions = await session_mgr.get_recent_sessions(10)
        assert sessions == []

    async def test_returns_sessions(self, session_mgr):
        await session_mgr.create_session()
        await session_mgr.create_session()
        sessions = await session_mgr.get_recent_sessions(10)
        assert len(sessions) == 2

    async def test_limit_respected(self, session_mgr):
        for _ in range(5):
            await session_mgr.create_session()
        sessions = await session_mgr.get_recent_sessions(3)
        assert len(sessions) == 3


# ──────────────────────────────────────────────────────────────────────
# Export Tests
# ──────────────────────────────────────────────────────────────────────


class TestExportJson:
    async def test_export_session_json(self, session_mgr, sample_mgr):
        from dataclasses import asdict
        from datetime import datetime

        from openwalk.protocol.messages import DataMessage

        sid = await session_mgr.create_session()
        msg = DataMessage(
            timestamp=datetime.now(),
            flag=0,
            steps=10,
            distance_raw=50,
            belt_revs=4,
            motor_pulses=100,
            speed=10,
            belt_state=1,
            raw_hex="5b0d050a003200040064000a01005d",
        )
        await sample_mgr.insert_sample(sid, msg, cumulative_steps=10)

        session = await session_mgr.get_session(sid)
        samples = await sample_mgr.get_samples(sid)

        assert session is not None
        export_data = {
            "session": asdict(session),
            "samples": [asdict(s) for s in samples],
        }

        # Verify it's valid JSON
        json_str = json.dumps(export_data, indent=2)
        parsed = json.loads(json_str)
        assert parsed["session"]["id"] == sid
        assert len(parsed["samples"]) == 1
        assert parsed["samples"][0]["steps"] == 10
