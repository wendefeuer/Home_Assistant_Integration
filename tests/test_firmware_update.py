"""Tests for OpenEPaperLink AP firmware status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aiohttp
from homeassistant.const import STATE_OFF, STATE_ON
import pytest

from custom_components.open_epaper_link import coordinator, firmware
from custom_components.open_epaper_link.firmware import FirmwareRelease
from custom_components.open_epaper_link.update import OpenEPaperLinkAPFirmwareUpdate


ENVIRONMENT = "ESP32_S3_16_8_YELLOW_AP"
RELEASE_URL = "https://github.com/OpenEPaperLink/OpenEPaperLink/releases/tag/2.91"


class FakeResponse:
    """Small aiohttp response stand-in."""

    def __init__(self, data: dict) -> None:
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict:
        return self._data


class FakeSession:
    """Record HTTP requests and return predetermined JSON."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(self.data)


def release_data(
    version: str = "2.91",
    *,
    environment: str = ENVIRONMENT,
    published_at: str = "2026-07-07T16:12:09Z",
) -> dict:
    """Return a minimal valid GitHub latest-release response."""
    return {
        "tag_name": version,
        "published_at": published_at,
        "html_url": RELEASE_URL,
        "assets": [{"name": f"{environment}.bin"}],
    }


def fake_hub(
    installed_version: str,
    *,
    build_time: datetime | None = None,
    entry_id: str = "entry-a",
):
    """Return the minimum hub contract required by the update entity."""
    return SimpleNamespace(
        entry=SimpleNamespace(entry_id=entry_id),
        ap_build_version=installed_version,
        ap_build_time=build_time,
        ap_env=ENVIRONMENT,
        ap_config={"repo": "OpenEPaperLink/OpenEPaperLink"},
        host="192.0.2.10",
        online=True,
    )


@pytest.mark.asyncio
async def test_ap_sysinfo_retains_firmware_metadata() -> None:
    """The existing sysinfo request should retain all firmware fields."""
    hub = object.__new__(coordinator.Hub)
    hub.host = "192.0.2.10"
    hub._session = FakeSession(
        {
            "env": ENVIRONMENT,
            "buildversion": "2.9",
            "buildtime": "1782944551",
            "sha": "a6a290c",
        }
    )

    await hub.async_update_ap_info()

    assert hub.ap_env == ENVIRONMENT
    assert hub.ap_build_version == "2.9"
    assert hub.ap_build_time == datetime(
        2026, 7, 1, 22, 22, 31, tzinfo=timezone.utc
    )
    assert hub.ap_build_sha == "a6a290c"


@pytest.mark.parametrize("value", [None, "", "not-a-timestamp", 0, -1])
def test_invalid_ap_build_time_is_unknown(value: object) -> None:
    assert coordinator.Hub._parse_ap_build_time(value) is None


@pytest.mark.asyncio
async def test_release_lookup_is_cached_per_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple APs using one repository should share one GitHub request."""
    hass = SimpleNamespace(data={})
    session = FakeSession(release_data())
    monkeypatch.setattr(firmware, "async_get_clientsession", lambda _hass: session)

    first = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )
    second = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )

    assert first == second
    assert first is not None
    assert first.version == "2.91"
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_custom_repository_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    hass = SimpleNamespace(data={})
    session = FakeSession(release_data())
    monkeypatch.setattr(firmware, "async_get_clientsession", lambda _hass: session)

    result = await firmware.async_get_latest_firmware_release(
        hass, "example/custom-firmware", ENVIRONMENT
    )

    assert result is not None
    assert session.urls == [
        "https://api.github.com/repos/example/custom-firmware/releases/latest"
    ]


@pytest.mark.asyncio
async def test_missing_firmware_asset_returns_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = SimpleNamespace(data={})
    session = FakeSession(release_data(environment="OTHER_AP"))
    monkeypatch.setattr(firmware, "async_get_clientsession", lambda _hass: session)

    result = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )

    assert result is None


@pytest.mark.asyncio
async def test_github_failure_returns_unknown_without_false_current_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, *_args, **_kwargs):
            self.calls += 1
            raise aiohttp.ClientConnectionError("GitHub unavailable")

    hass = SimpleNamespace(data={})
    session = FailingSession()
    monkeypatch.setattr(
        firmware, "async_get_clientsession", lambda _hass: session
    )

    result = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )
    repeated = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )

    assert result is None
    assert repeated is None
    assert session.calls == 1
    cached = hass.data["open_epaper_link"][firmware.FIRMWARE_RELEASE_CACHE_KEY]
    assert cached["OpenEPaperLink/OpenEPaperLink"].release is None


@pytest.mark.asyncio
async def test_github_rate_limit_returns_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateLimitedResponse(FakeResponse):
        def raise_for_status(self) -> None:
            raise aiohttp.ClientResponseError(
                SimpleNamespace(real_url="https://api.github.com/rate-limit"),
                (),
                status=403,
                message="rate limit exceeded",
            )

    class RateLimitedSession:
        def get(self, *_args, **_kwargs):
            return RateLimitedResponse({})

    hass = SimpleNamespace(data={})
    monkeypatch.setattr(
        firmware, "async_get_clientsession", lambda _hass: RateLimitedSession()
    )

    result = await firmware.async_get_latest_firmware_release(
        hass, "OpenEPaperLink/OpenEPaperLink", ENVIRONMENT
    )

    assert result is None


def test_firmware_update_state_uses_version_and_build_time() -> None:
    release = FirmwareRelease(
        version="2.91",
        published_at=datetime(2026, 7, 7, 16, 12, 9, tzinfo=timezone.utc),
        release_url=RELEASE_URL,
        asset_names=frozenset({f"{ENVIRONMENT}.bin"}),
    )

    outdated = OpenEPaperLinkAPFirmwareUpdate(fake_hub("2.9"))
    outdated._release = release
    assert outdated.state == STATE_ON
    assert outdated.installed_version == "2.9"
    assert outdated.latest_version == "2.91"

    current = OpenEPaperLinkAPFirmwareUpdate(fake_hub("2.91"))
    current._release = release
    assert current.state == STATE_OFF

    development = OpenEPaperLinkAPFirmwareUpdate(
        fake_hub(
            "custom",
            build_time=release.published_at + timedelta(hours=1),
        )
    )
    development._release = release
    assert development.state == STATE_OFF


def test_ap_update_entities_keep_independent_versions() -> None:
    release = FirmwareRelease(
        version="2.91",
        published_at=None,
        release_url=RELEASE_URL,
        asset_names=frozenset({f"{ENVIRONMENT}.bin"}),
    )
    first = OpenEPaperLinkAPFirmwareUpdate(fake_hub("2.9", entry_id="entry-a"))
    second = OpenEPaperLinkAPFirmwareUpdate(fake_hub("2.91", entry_id="entry-b"))
    first._release = release
    second._release = release

    assert first.unique_id == "entry-a_firmware"
    assert second.unique_id == "entry-b_firmware"
    assert first.state == STATE_ON
    assert second.state == STATE_OFF


def test_unknown_latest_version_keeps_update_state_unknown() -> None:
    entity = OpenEPaperLinkAPFirmwareUpdate(fake_hub("2.9"))

    assert entity.installed_version == "2.9"
    assert entity.latest_version is None
    assert entity.state is None
