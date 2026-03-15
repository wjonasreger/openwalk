"""BLE device scanner for InMovement Unsit treadmill.

Handles device discovery by name, RSSI-based sorting,
and UUID caching for faster reconnects on macOS.
"""

import json
import logging
from pathlib import Path

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from openwalk.ble.characteristics import DEVICE_NAME

logger = logging.getLogger(__name__)

SCAN_TIMEOUT = 20.0  # seconds
CACHE_FILE = Path.home() / ".openwalk" / "device_cache.json"


async def find_treadmill(
    device_name: str = DEVICE_NAME,
    timeout: float = SCAN_TIMEOUT,
) -> str | None:
    """Scan for the treadmill by name and return its address.

    Args:
        device_name: BLE advertisement name to search for.
        timeout: Scan timeout in seconds.

    Returns:
        Device address (CoreBluetooth UUID on macOS) or None if not found.
    """
    logger.info("Scanning for %s (timeout: %.0fs)...", device_name, timeout)

    device = await BleakScanner.find_device_by_name(device_name, timeout=timeout)

    if device:
        logger.info("Found %s at %s", device_name, device.address)
        return device.address

    logger.warning("%s not found", device_name)
    return None


async def find_all_treadmills(
    device_name: str = DEVICE_NAME,
    timeout: float = SCAN_TIMEOUT,
) -> list[tuple[str, int]]:
    """Find all treadmills matching the name, sorted by RSSI.

    Args:
        device_name: BLE advertisement name to search for.
        timeout: Scan timeout in seconds.

    Returns:
        List of (address, rssi) tuples sorted by strongest signal first.
    """
    logger.info("Scanning for all %s devices...", device_name)

    devices: dict[str, tuple[BLEDevice, AdvertisementData]] = await BleakScanner.discover(
        timeout=timeout, return_adv=True
    )

    matches: list[tuple[str, int]] = []
    for _address, (device, adv_data) in devices.items():
        if device.name and device.name == device_name:
            matches.append((device.address, adv_data.rssi))
            logger.info("Found %s at %s (RSSI: %d dBm)", device_name, device.address, adv_data.rssi)

    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def save_device_uuid(device_name: str, uuid: str) -> None:
    """Save discovered device UUID to cache for faster reconnects.

    Args:
        device_name: Device name key.
        uuid: Device address/UUID to cache.
    """
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    cache: dict[str, str] = {}
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt device cache, resetting")

    cache[device_name] = uuid
    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    logger.debug("Cached UUID for %s: %s", device_name, uuid)


def load_device_uuid(device_name: str) -> str | None:
    """Load cached device UUID.

    Args:
        device_name: Device name key.

    Returns:
        Cached UUID or None if not cached.
    """
    if not CACHE_FILE.exists():
        return None

    try:
        cache = json.loads(CACHE_FILE.read_text())
        uuid: str | None = cache.get(device_name)
        if uuid:
            logger.debug("Loaded cached UUID for %s: %s", device_name, uuid)
        return uuid
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read device cache")
        return None


async def discover_or_use_cached(
    device_name: str = DEVICE_NAME,
    timeout: float = SCAN_TIMEOUT,
) -> str | None:
    """Try cached UUID first, fall back to BLE scan.

    On successful scan, caches the UUID for future use.

    Args:
        device_name: BLE advertisement name to search for.
        timeout: Scan timeout in seconds.

    Returns:
        Device address or None if not found.
    """
    uuid = load_device_uuid(device_name)
    if uuid:
        logger.info("Using cached UUID for %s: %s", device_name, uuid)
        return uuid

    uuid = await find_treadmill(device_name, timeout)
    if uuid:
        save_device_uuid(device_name, uuid)

    return uuid
