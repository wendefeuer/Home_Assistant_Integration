"""Tests for OpenEPaperLink multi-AP routing."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import requests

from homeassistant.exceptions import HomeAssistantError

from custom_components.open_epaper_link import coordinator
from custom_components.open_epaper_link.hub_manager import (
    MultiHubManager,
    ap_identifier,
)
from custom_components.open_epaper_link.util import get_hub_for_tag

TAG = "0011223344556677"


@dataclass
class FakeEntry:
    entry_id: str


class FakeHub:
    """Small Hub stand-in exposing only the router contract."""

    def __init__(
        self,
        entry_id: str,
        host: str,
        *,
        last_seen: int,
        online: bool = True,
        tag_online: bool = True,
        is_external: bool | None = None,
        tags: list[str] | None = None,
        blacklisted: list[str] | None = None,
    ) -> None:
        self.entry = FakeEntry(entry_id)
        self.host = host
        self.online = online
        self.tags = tags if tags is not None else [TAG]
        self._blacklisted = blacklisted or []
        self._tag_online = tag_online
        self._data = {
            TAG: {
                "last_seen": last_seen,
                "host": host,
                "is_external": is_external,
            }
        }

    def get_tag_data(self, tag_mac: str) -> dict:
        return self._data.get(tag_mac, {})

    def get_blacklisted_tags(self) -> list[str]:
        return self._blacklisted

    def is_tag_online(self, tag_mac: str) -> bool:
        return tag_mac in self.tags and self._tag_online


class FakeHass:
    def __init__(self) -> None:
        self.data = {}


def test_freshest_active_ap_is_selected() -> None:
    manager = MultiHubManager(FakeHass())
    hub_a = FakeHub("hub-a", "192.0.2.143", last_seen=100)
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=200)
    manager.register_hub(hub_a)
    manager.register_hub(hub_b)

    assert manager.resolve_tag_hub(TAG) is hub_b
    assert manager.get_tag_data(TAG)["host"] == "192.0.2.166"


def test_inactive_duplicate_does_not_steal_route() -> None:
    manager = MultiHubManager(FakeHass())
    hub_a = FakeHub(
        "hub-a",
        "192.0.2.143",
        last_seen=300,
        tag_online=False,
    )
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=200)
    manager.register_hub(hub_a)
    manager.register_hub(hub_b)

    assert manager.resolve_tag_hub(TAG) is hub_b


def test_external_duplicate_does_not_steal_route_on_equal_last_seen() -> None:
    """A replicated AP database entry cannot deliver to the physical tag."""
    manager = MultiHubManager(FakeHass())
    external_hub = FakeHub(
        "entry-z",
        "192.0.2.143",
        last_seen=300,
        is_external=True,
    )
    local_hub = FakeHub(
        "entry-a",
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    manager.register_hub(external_hub)
    manager.register_hub(local_hub)

    assert manager.resolve_tag_hub(TAG) is local_hub


def test_external_duplicate_does_not_steal_route_when_fresher() -> None:
    manager = MultiHubManager(FakeHass())
    external_hub = FakeHub(
        "entry-z",
        "192.0.2.143",
        last_seen=400,
        is_external=True,
    )
    local_hub = FakeHub(
        "entry-a",
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    manager.register_hub(external_hub)
    manager.register_hub(local_hub)

    assert manager.resolve_tag_hub(TAG) is local_hub


def test_external_only_tag_fails_closed_for_write_routing() -> None:
    manager = MultiHubManager(FakeHass())
    manager.register_hub(
        FakeHub(
            "entry-z",
            "192.0.2.143",
            last_seen=400,
            is_external=True,
        )
    )

    with pytest.raises(HomeAssistantError):
        manager.resolve_tag_hub(TAG)


def test_offline_ap_falls_back_to_active_ap() -> None:
    manager = MultiHubManager(FakeHass())
    hub_a = FakeHub(
        "hub-a",
        "192.0.2.143",
        last_seen=500,
        online=False,
    )
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=100)
    manager.register_hub(hub_a)
    manager.register_hub(hub_b)

    assert manager.resolve_tag_hub(TAG) is hub_b


def test_no_online_ap_fails_closed() -> None:
    manager = MultiHubManager(FakeHass())
    manager.register_hub(
        FakeHub("hub-a", "192.0.2.143", last_seen=100, online=False)
    )

    with pytest.raises(HomeAssistantError):
        manager.resolve_tag_hub(TAG)


def test_blacklisted_copy_does_not_hide_other_ap() -> None:
    manager = MultiHubManager(FakeHass())
    manager.register_hub(
        FakeHub(
            "hub-a",
            "192.0.2.143",
            last_seen=300,
            blacklisted=[TAG],
        )
    )
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=200)
    manager.register_hub(hub_b)

    assert manager.resolve_tag_hub(TAG) is hub_b
    assert manager.tag_exists_elsewhere(TAG, exclude_entry_id="hub-a")


def test_service_lookup_uses_manager_route() -> None:
    hass = FakeHass()
    manager = MultiHubManager(hass)
    hass.data["open_epaper_link"] = {"hub_manager": manager}
    hub_a = FakeHub("hub-a", "192.0.2.143", last_seen=100, tag_online=False)
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=200)
    manager.register_hub(hub_a)
    manager.register_hub(hub_b)

    assert get_hub_for_tag(hass, f"open_epaper_link.{TAG}") is hub_b


def test_ap_identifiers_are_config_entry_specific() -> None:
    assert ap_identifier("entry-a") == "ap_entry-a"
    assert ap_identifier("entry-a") != ap_identifier("entry-b")


def test_hub_storage_is_config_entry_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    stores: list[str] = []

    class FakeStore:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, _hass, _version, key, **_kwargs):
            stores.append(key)

    fake_hass = SimpleNamespace(bus=SimpleNamespace())
    entry = SimpleNamespace(
        entry_id="entry-a",
        data={"host": "192.0.2.166"},
        options={},
    )
    monkeypatch.setattr(coordinator, "Store", FakeStore)
    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda _hass: object())

    hub = coordinator.Hub(fake_hass, entry)

    assert hub.storage_key == "open_epaper_link_tags_entry-a"
    assert "open_epaper_link_tags_entry-a" in stores
    assert "open_epaper_link_tags" in stores


@pytest.mark.asyncio
async def test_ap_reboot_accepts_firmware_read_timeout() -> None:
    """The AP restarts before its reboot HTTP response can be completed."""
    hub = object.__new__(coordinator.Hub)
    hub.host = "192.0.2.143"
    hub._run_ap_command = AsyncMock(
        side_effect=requests.exceptions.ReadTimeout("AP is restarting")
    )

    assert await hub.reboot_ap()
