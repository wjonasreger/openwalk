"""Python wrapper for the Swift HealthKit bridge CLI.

Calls the `openwalk-health-bridge` binary via subprocess to write
treadmill session data to Apple Health.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BINARY_NAME = "openwalk-health-bridge"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BridgeNotFoundError(Exception):
    """The Swift bridge binary could not be found."""


class AuthError(Exception):
    """HealthKit authorization was denied (exit code 1)."""


class ValidationError(Exception):
    """Input data was invalid (exit code 2)."""


class WriteError(Exception):
    """HealthKit write operation failed (exit code 3)."""


# Map exit codes to exception types
_EXIT_CODE_ERRORS: dict[int, type[Exception]] = {
    1: AuthError,
    2: ValidationError,
    3: WriteError,
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkResult:
    """Result from writing a chunk to HealthKit."""

    steps_uuid: str
    distance_uuid: str
    calories_uuid: str
    was_existing: bool = False


@dataclass(frozen=True)
class WorkoutResult:
    """Result from writing a workout to HealthKit."""

    workout_uuid: str
    was_existing: bool = False


# ---------------------------------------------------------------------------
# Bridge wrapper
# ---------------------------------------------------------------------------


class HealthKitBridge:
    """Python wrapper for the Swift HealthKit bridge CLI.

    Locates the `openwalk-health-bridge` binary and provides async methods
    for writing chunks and workouts to HealthKit via subprocess calls.

    Args:
        binary_path: Explicit path to the bridge binary. If None, searches
            PATH using shutil.which().
    """

    def __init__(self, binary_path: str | None = None) -> None:
        if binary_path:
            self._binary = Path(binary_path)
        else:
            found = shutil.which(BINARY_NAME)
            self._binary = Path(found) if found else None  # type: ignore[assignment]

    @property
    def available(self) -> bool:
        """Whether the Swift bridge binary was found."""
        return self._binary is not None and self._binary.exists()

    def _check_available(self) -> None:
        if not self.available:
            raise BridgeNotFoundError(
                f"Swift bridge binary '{BINARY_NAME}' not found. "
                "Build and install from openwalk-health-bridge/ directory."
            )

    async def write_chunk(self, chunk_data: dict[str, object]) -> ChunkResult:
        """Write a 60-second chunk to HealthKit.

        Args:
            chunk_data: Dict with keys: session_id, chunk_index, start, end,
                steps, distance_miles, calories.

        Returns:
            ChunkResult with HealthKit UUIDs.

        Raises:
            BridgeNotFoundError: Bridge binary not found.
            AuthError: HealthKit authorization denied.
            ValidationError: Invalid input data.
            WriteError: HealthKit write failed.
        """
        self._check_available()
        result = await self._call_bridge("write-chunk", chunk_data)
        return ChunkResult(
            steps_uuid=result["steps_uuid"],
            distance_uuid=result["distance_uuid"],
            calories_uuid=result["calories_uuid"],
            was_existing=result.get("was_existing", False),
        )

    async def write_workout(self, workout_data: dict[str, object]) -> WorkoutResult:
        """Write a session workout summary to HealthKit.

        Args:
            workout_data: Dict with keys: session_id, start, end,
                duration_seconds, total_steps, total_distance_miles, total_calories.

        Returns:
            WorkoutResult with HealthKit workout UUID.

        Raises:
            BridgeNotFoundError: Bridge binary not found.
            AuthError: HealthKit authorization denied.
            ValidationError: Invalid input data.
            WriteError: HealthKit write failed.
        """
        self._check_available()
        result = await self._call_bridge("write-workout", workout_data)
        return WorkoutResult(
            workout_uuid=result["workout_uuid"],
            was_existing=result.get("was_existing", False),
        )

    async def _call_bridge(
        self, command: str, data: dict[str, object]
    ) -> dict[str, Any]:
        """Call the Swift bridge subprocess with JSON data.

        Writes data to a temp file, calls the binary, parses stdout JSON.
        """
        assert self._binary is not None

        # Write JSON to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="openwalk_"
        ) as tmp:
            json.dump(data, tmp)
        try:

            proc = await asyncio.create_subprocess_exec(
                str(self._binary),
                command,
                tmp.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            returncode = proc.returncode or 0
            if returncode != 0:
                error_msg = stderr.decode().strip() if stderr else f"Exit code {returncode}"
                error_cls = _EXIT_CODE_ERRORS.get(returncode, WriteError)
                raise error_cls(error_msg)

            # Parse JSON response
            try:
                result: dict[str, Any] = json.loads(stdout.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise WriteError(f"Invalid JSON response from bridge: {exc}") from exc

            return result
        finally:
            Path(tmp.name).unlink(missing_ok=True)
