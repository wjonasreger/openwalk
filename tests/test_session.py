"""Tests for session module: calories, live state, and orchestrator."""

import asyncio
import contextlib
from datetime import datetime, timedelta

import pytest

from openwalk.protocol.messages import (
    DataMessage,
    IdleMessage,
    SpeedMessage,
    TruncatedFrame,
)
from openwalk.session.calories import (
    UserProfile,
    bmr_kcal_per_min,
    gross_kcal_per_min,
    gross_metabolic_rate_wpkg,
    net_kcal_per_min,
)
from openwalk.session.orchestrator import SessionOrchestrator
from openwalk.session.state import LiveSessionState
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager
from openwalk.storage.sessions import SessionManager

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")


@pytest.fixture
def default_profile() -> UserProfile:
    return UserProfile()


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


@pytest.fixture
async def orchestrator(session_mgr, sample_mgr, profile):
    return SessionOrchestrator(session_mgr, sample_mgr, profile, inactivity_timeout=5.0)


def _make_data_msg(
    steps: int = 10,
    distance_raw: int = 50,
    speed: int = 10,
    belt_state: int = 1,
    belt_revs: int = 4,
    belt_cadence: int = 25,
    flag: int = 0,
    timestamp: datetime | None = None,
) -> DataMessage:
    """Create a DataMessage for testing."""
    ts = timestamp or datetime.now()
    raw_hex = "5b0d050019003200040000000a01005d"
    return DataMessage(
        timestamp=ts,
        flag=flag,
        belt_cadence=belt_cadence,
        distance_raw=distance_raw,
        belt_revs=belt_revs,
        steps=steps,
        speed=speed,
        belt_state=belt_state,
        raw_hex=raw_hex,
    )


def _make_idle_msg(timestamp: datetime | None = None) -> IdleMessage:
    ts = timestamp or datetime.now()
    return IdleMessage(
        timestamp=ts,
        state_byte1=1,
        state_byte2=1,
        state_byte3=0,
        raw_hex="5b0703010100005d",
    )


def _make_speed_msg(speed: int = 10, timestamp: datetime | None = None) -> SpeedMessage:
    ts = timestamp or datetime.now()
    return SpeedMessage(timestamp=ts, speed=speed, raw_hex="5b05110a005d")


def _make_truncated_frame(timestamp: datetime | None = None) -> TruncatedFrame:
    ts = timestamp or datetime.now()
    return TruncatedFrame(
        timestamp=ts,
        expected_size=16,
        actual_size=5,
        variant="DATA_5",
        raw_hex="5b10050a005d",
    )


def _build_ble_notification(
    steps: int = 10,
    distance_lo: int = 0x32,
    distance_hi: int = 0x00,
    belt_revs: int = 4,
    belt_cadence: int = 25,
    speed: int = 10,
    belt_state: int = 1,
    flag: int = 0,
) -> bytes:
    """Build a raw BLE notification containing a single 16-byte DATA frame.

    Format: [5B][0D][05][flag][belt_cadence][00][dist_lo][dist_hi]
            [belt_revs][00][steps_hi][steps_lo][speed][belt_state][00][5D]

    Steps (bytes 10-11) are big-endian: high byte first.
    """
    steps_hi = (steps >> 8) & 0xFF
    steps_lo = steps & 0xFF
    return bytes(
        [
            0x5B,
            0x0D,
            0x05,
            flag,
            belt_cadence,
            0x00,
            distance_lo,
            distance_hi,
            belt_revs,
            0x00,
            steps_hi,
            steps_lo,
            speed,
            belt_state,
            0x00,
            0x5D,
        ]
    )


# ──────────────────────────────────────────────────────────────────────
# Calorie Tests
# ──────────────────────────────────────────────────────────────────────


class TestGrossMetabolicRate:
    def test_zero_speed_returns_standing_cost(self):
        assert gross_metabolic_rate_wpkg(0.0) == 1.44

    def test_negative_speed_returns_standing_cost(self):
        assert gross_metabolic_rate_wpkg(-1.0) == 1.44

    def test_one_mph(self):
        rate = gross_metabolic_rate_wpkg(1.0)
        assert rate > 1.44
        assert 2.5 < rate < 3.5

    def test_two_mph(self):
        rate = gross_metabolic_rate_wpkg(2.0)
        assert rate > gross_metabolic_rate_wpkg(1.0)

    def test_monotonically_increasing(self):
        r1 = gross_metabolic_rate_wpkg(0.5)
        r2 = gross_metabolic_rate_wpkg(1.0)
        r3 = gross_metabolic_rate_wpkg(1.5)
        r4 = gross_metabolic_rate_wpkg(2.0)
        assert r1 < r2 < r3 < r4


class TestGrossKcalPerMin:
    def test_heavier_person_burns_more(self, profile):
        light = UserProfile(weight_lbs=120.0, height_inches=65.0, age_years=30, gender="female")
        heavy = UserProfile(weight_lbs=250.0, height_inches=72.0, age_years=30, gender="male")
        assert gross_kcal_per_min(1.0, heavy) > gross_kcal_per_min(1.0, light)

    def test_zero_speed(self, profile):
        rate = gross_kcal_per_min(0.0, profile)
        assert rate > 0  # Still burns calories standing

    def test_known_value(self):
        """Validate against worked example from calorie spec (Example 1)."""
        p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")
        rate = gross_kcal_per_min(1.0, p)
        # Expected: ~2.73 kcal/min from spec
        assert 2.5 < rate < 3.0


class TestBmrKcalPerMin:
    def test_male(self, profile):
        rate = bmr_kcal_per_min(profile)
        assert rate > 0
        # Male, 150 lbs, 68", 40 years → ~1564.9 kcal/day → ~1.087 kcal/min
        assert 1.0 < rate < 1.2

    def test_female(self):
        p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="female")
        rate = bmr_kcal_per_min(p)
        # Female has lower BMR (minus 161 vs plus 5)
        male_p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")
        assert rate < bmr_kcal_per_min(male_p)


class TestNetKcalPerMin:
    def test_positive(self, profile):
        net = net_kcal_per_min(1.0, profile)
        assert net > 0

    def test_never_negative(self, profile):
        net = net_kcal_per_min(0.0, profile)
        assert net >= 0

    def test_net_less_than_gross(self, profile):
        net = net_kcal_per_min(1.0, profile)
        gross = gross_kcal_per_min(1.0, profile)
        assert net < gross

    def test_known_value(self):
        """Validate against worked example from calorie spec (Example 1)."""
        p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")
        net = net_kcal_per_min(1.0, p)
        # Expected: ~1.64 kcal/min net from spec (gross ~2.73 - BMR ~1.09)
        assert 1.4 < net < 1.9


class TestUserProfile:
    def test_weight_conversion(self):
        p = UserProfile(weight_lbs=220.0)
        assert abs(p.weight_kg - 99.79) < 0.1

    def test_height_conversion(self):
        p = UserProfile(height_inches=72.0)
        assert abs(p.height_cm - 182.88) < 0.1

    def test_default_values(self, default_profile):
        assert default_profile.weight_lbs == 275.0
        assert default_profile.gender == "male"


# ──────────────────────────────────────────────────────────────────────
# LiveSessionState Tests
# ──────────────────────────────────────────────────────────────────────


class TestLiveSessionState:
    def test_elapsed_no_session(self):
        s = LiveSessionState()
        assert s.elapsed_seconds == 0.0
        assert s.elapsed_formatted == "00:00"

    def test_elapsed_formatted_minutes(self):
        s = LiveSessionState()
        s.started_at = datetime.now() - timedelta(seconds=125)
        s.last_data_at = datetime.now()
        assert s.elapsed_formatted == "02:05"

    def test_elapsed_formatted_hours(self):
        s = LiveSessionState()
        s.started_at = datetime.now() - timedelta(seconds=3725)
        s.last_data_at = datetime.now()
        assert s.elapsed_formatted == "1:02:05"

    def test_distance_miles(self):
        s = LiveSessionState()
        s.distance_raw = 142
        assert abs(s.distance_miles - 1.42) < 0.01

    def test_speed_mph(self):
        s = LiveSessionState()
        s.speed = 15
        assert s.speed_mph == 1.5

    def test_is_belt_running(self):
        s = LiveSessionState()
        assert not s.is_belt_running
        s.belt_state = 1
        assert s.is_belt_running

    def test_step_rate_empty(self):
        s = LiveSessionState()
        assert s.step_rate == 0.0

    def test_step_rate_calculation(self):
        s = LiveSessionState()
        now = datetime.now()
        s.record_step_sample(now - timedelta(seconds=5), 0)
        s.record_step_sample(now, 100)
        rate = s.step_rate
        # 100 steps in 5 seconds = 1200 steps/min
        assert abs(rate - 1200.0) < 1.0

    def test_step_rate_window_too_short(self):
        s = LiveSessionState()
        now = datetime.now()
        s.record_step_sample(now - timedelta(seconds=1), 0)
        s.record_step_sample(now, 10)
        # Window is 1 second, minimum is 3 seconds
        assert s.step_rate == 0.0

    def test_calorie_accumulation(self):
        s = LiveSessionState()
        p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")
        now = datetime.now()

        # Simulate active stepping so step_rate > 0
        s.record_step_sample(now, 10)
        s.record_step_sample(now + timedelta(seconds=5), 20)
        s._last_step_change_at = now + timedelta(seconds=5)

        # First call sets the timestamp but doesn't accumulate
        s.accumulate_calories(now + timedelta(seconds=5), 1.0, p)
        assert s.gross_calories == 0.0

        # Second call accumulates over time delta
        s.accumulate_calories(now + timedelta(seconds=6), 1.0, p)
        assert s.gross_calories > 0.0
        assert s.net_calories > 0.0
        assert s.net_calories < s.gross_calories

    def test_calorie_zero_when_not_stepping(self):
        """Calories should not accumulate when step_rate is 0."""
        s = LiveSessionState()
        p = UserProfile(weight_lbs=150.0, height_inches=68.0, age_years=40, gender="male")
        now = datetime.now()

        # No step activity — step_rate should be 0
        s.accumulate_calories(now, 1.0, p)
        s.accumulate_calories(now + timedelta(minutes=1), 1.0, p)
        assert s.gross_calories == 0.0
        assert s.net_calories == 0.0

    def test_max_speed_default(self):
        s = LiveSessionState()
        assert s.max_speed == 0

    def test_avg_speed_mph_no_data(self):
        s = LiveSessionState()
        assert s.avg_speed_mph == 0.0

    def test_avg_speed_mph_calculation(self):
        s = LiveSessionState()
        s.started_at = datetime.now() - timedelta(hours=1)
        s.last_data_at = datetime.now()
        s.distance_raw = 100  # 1.0 miles
        # 1.0 miles in 1 hour = 1.0 mph
        assert abs(s.avg_speed_mph - 1.0) < 0.05

    def test_reset(self):
        s = LiveSessionState()
        s.session_id = 42
        s.total_steps = 500
        s.max_speed = 15
        s.gross_calories = 100.0
        s.data_count = 200

        s.reset()

        assert s.session_id is None
        assert s.total_steps == 0
        assert s.max_speed == 0
        assert s.gross_calories == 0.0
        assert s.data_count == 0


# ──────────────────────────────────────────────────────────────────────
# SessionOrchestrator Tests
# ──────────────────────────────────────────────────────────────────────


class TestOrchestratorDataHandling:
    async def test_data_message_updates_state(self, orchestrator):
        data = _build_ble_notification(steps=10, speed=15, belt_state=1)
        orchestrator.handle_raw_data(data)

        s = orchestrator.state
        assert s.total_steps == 10
        assert s.speed == 15
        assert s.belt_state == 1
        assert s.data_count == 1

    async def test_multiple_data_messages(self, orchestrator):
        data1 = _build_ble_notification(steps=10, speed=10, belt_state=1)
        data2 = _build_ble_notification(steps=20, speed=12, belt_state=1)
        orchestrator.handle_raw_data(data1)
        orchestrator.handle_raw_data(data2)

        assert orchestrator.state.total_steps == 20
        assert orchestrator.state.speed == 12
        assert orchestrator.state.data_count == 2

    async def test_counter_wrap_around(self, orchestrator):
        # Steps is now uint16 (0-65535), wrap threshold is 60000
        data1 = _build_ble_notification(steps=65530, belt_state=1)
        data2 = _build_ble_notification(steps=5, belt_state=1)
        orchestrator.handle_raw_data(data1)
        orchestrator.handle_raw_data(data2)

        # 65530 -> 5 with wrap: total should be 65541 (65536 + 5)
        assert orchestrator.state.total_steps == 65541

    async def test_max_speed_tracked(self, orchestrator):
        data1 = _build_ble_notification(steps=5, speed=10, belt_state=1)
        data2 = _build_ble_notification(steps=10, speed=18, belt_state=1)
        data3 = _build_ble_notification(steps=15, speed=12, belt_state=1)
        orchestrator.handle_raw_data(data1)
        orchestrator.handle_raw_data(data2)
        orchestrator.handle_raw_data(data3)

        assert orchestrator.state.max_speed == 18
        assert orchestrator.state.speed == 12  # current speed


class TestOrchestratorIdle:
    async def test_idle_counted(self, orchestrator):
        # IDLE frame: [5B][04][03][state1][state2][state3][5D] = 7 bytes, length=4
        idle_data = bytes([0x5B, 0x04, 0x03, 0x01, 0x01, 0x00, 0x5D])
        orchestrator.handle_raw_data(idle_data)

        assert orchestrator.state.idle_count == 1


class TestOrchestratorSpeed:
    async def test_speed_message_updates(self, orchestrator):
        # SPEED frame: [5B][02][11][speed][5D] = 5 bytes, length=2
        speed_data = bytes([0x5B, 0x02, 0x11, 0x0F, 0x5D])
        orchestrator.handle_raw_data(speed_data)

        assert orchestrator.state.speed == 15
        assert orchestrator.state.speed_count == 1


class TestOrchestratorConnectionState:
    async def test_state_change_stored(self, orchestrator):
        from openwalk.ble.connection import ConnectionState

        orchestrator.handle_state_change(ConnectionState.SUBSCRIBED, "Ready")

        assert orchestrator.conn_state == ConnectionState.SUBSCRIBED
        assert orchestrator.conn_message == "Ready"
        assert orchestrator.state.conn_state_name == "SUBSCRIBED"


class TestOrchestratorSessionLifecycle:
    async def test_auto_start_on_belt_running(self, orchestrator):
        """Belt running with no active session should queue a session start."""
        data = _build_ble_notification(steps=5, belt_state=1)
        orchestrator.handle_raw_data(data)

        # Process the queue to execute the start
        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.1)
        orchestrator.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert orchestrator.state.session_id is not None

    async def test_no_auto_start_belt_stopped(self, orchestrator):
        """Belt stopped should not start a session."""
        data = _build_ble_notification(steps=5, belt_state=0)
        orchestrator.handle_raw_data(data)

        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.1)
        orchestrator.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert orchestrator.state.session_id is None

    async def test_no_double_start(self, orchestrator):
        """Second belt-running message should not create a second session."""
        data1 = _build_ble_notification(steps=5, belt_state=1)
        data2 = _build_ble_notification(steps=10, belt_state=1)
        orchestrator.handle_raw_data(data1)

        # Process queue to start the session
        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.1)
        first_id = orchestrator.state.session_id

        # Send second message
        orchestrator.handle_raw_data(data2)
        await asyncio.sleep(0.1)

        orchestrator.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert orchestrator.state.session_id == first_id

    async def test_inactivity_auto_end(self, orchestrator):
        """Session should auto-end after inactivity timeout."""
        # Start a session
        data = _build_ble_notification(steps=5, belt_state=1)
        orchestrator.handle_raw_data(data)

        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.1)
        assert orchestrator.state.session_id is not None

        # Simulate belt stopping and time passing
        orchestrator.state.belt_state = 0
        orchestrator.state.last_data_at = datetime.now() - timedelta(seconds=10)

        await orchestrator.check_inactivity()
        await asyncio.sleep(0.1)

        orchestrator.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert orchestrator.state.session_id is None

    async def test_explicit_end_session(self, orchestrator):
        """Explicit end_session should finalize."""
        data = _build_ble_notification(steps=5, belt_state=1)
        orchestrator.handle_raw_data(data)

        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.1)
        assert orchestrator.state.session_id is not None

        await orchestrator.end_session()

        orchestrator.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert orchestrator.state.session_id is None

    async def test_recover_on_startup(self, orchestrator):
        """recover_on_startup should not raise."""
        await orchestrator.recover_on_startup()


class TestOrchestratorCalories:
    async def test_calorie_accumulation_across_messages(self, orchestrator):
        """Calories should accumulate as data messages arrive with active stepping."""
        now = datetime.now()

        # Seed the step window with enough history so step_rate > 0
        s = orchestrator.state
        s.record_step_sample(now - timedelta(seconds=5), 0)
        s.record_step_sample(now, 10)
        s._last_step_change_at = now

        data1 = _build_ble_notification(steps=15, speed=10, belt_state=1)
        orchestrator.handle_raw_data(data1)

        # Manually set timestamp to simulate time passing
        s.last_cal_timestamp = now - timedelta(minutes=1)
        # Keep step activity recent
        s._last_step_change_at = now

        data2 = _build_ble_notification(steps=25, speed=10, belt_state=1)
        orchestrator.handle_raw_data(data2)

        assert s.gross_calories > 0
        assert s.net_calories > 0


class TestOrchestratorDbQueue:
    async def test_samples_persisted(self, orchestrator, sample_mgr):
        """Data messages should be persisted to the database via the queue."""
        # First message triggers session start
        data1 = _build_ble_notification(steps=5, belt_state=1)
        orchestrator.handle_raw_data(data1)

        task = asyncio.create_task(orchestrator.process_db_queue())
        await asyncio.sleep(0.2)

        session_id = orchestrator.state.session_id
        assert session_id is not None

        # Second message should be persisted (session is now active)
        data2 = _build_ble_notification(steps=10, belt_state=1)
        orchestrator.handle_raw_data(data2)
        await asyncio.sleep(0.2)

        count = await sample_mgr.get_sample_count(session_id)
        assert count >= 1

        orchestrator.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
