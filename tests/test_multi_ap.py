"""Tests for OpenEPaperLink multi-AP routing."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests

from homeassistant.exceptions import HomeAssistantError

from custom_components.open_epaper_link import coordinator, hub_manager as hub_manager_module
from custom_components.open_epaper_link.button import TAG_EVENT_RESET_BUTTON_TYPES
from custom_components.open_epaper_link.const import SIGNAL_TAG_REBOOT
from custom_components.open_epaper_link.hub_manager import (
    MultiHubManager,
    ap_identifier,
)
from custom_components.open_epaper_link.sensor import (
    TAG_SENSOR_TYPES,
    _tag_event_count,
    _tag_event_last,
    _tag_has_battery,
)
from custom_components.open_epaper_link.util import get_hub_for_tag

TAG = "0011223344556677"


def test_tag_event_entities_are_disabled_by_default() -> None:
    """Displays without buttons or NFC should not receive active entities."""
    sensor_descriptions = [
        description
        for description in TAG_SENSOR_TYPES
        if description.key.startswith("event_")
    ]
    assert len(sensor_descriptions) == 6
    assert all(
        not description.entity_registry_enabled_default
        for description in sensor_descriptions
    )
    assert len(TAG_EVENT_RESET_BUTTON_TYPES) == 3
    assert all(
        not description.entity_registry_enabled_default
        for description in TAG_EVENT_RESET_BUTTON_TYPES
    )


@dataclass
class FakeEntry:
    entry_id: str
    data: dict = field(default_factory=dict)
    disabled_by: str | None = None


class FakeConfigEntries:
    def __init__(self, entries: list[FakeEntry]) -> None:
        self._entries = entries

    def async_entries(self, _domain: str) -> list[FakeEntry]:
        return self._entries


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
    def __init__(self, entries: list[FakeEntry] | None = None) -> None:
        self.data = {}
        if entries is not None:
            self.config_entries = FakeConfigEntries(entries)


def test_freshest_active_ap_is_selected() -> None:
    manager = MultiHubManager(FakeHass())
    hub_a = FakeHub("hub-a", "192.0.2.143", last_seen=100)
    hub_b = FakeHub("hub-b", "192.0.2.166", last_seen=200)
    manager.register_hub(hub_a)
    manager.register_hub(hub_b)

    assert manager.resolve_tag_hub(TAG) is hub_b
    assert manager.get_tag_data(TAG)["host"] == "192.0.2.166"


@pytest.mark.asyncio
async def test_tag_event_stats_persist_and_reset_only_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Button/NFC values survive a reload and retain timestamps on reset."""
    saved = None

    class FakeStore:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_args, **_kwargs):
            pass

        async def async_load(self):
            return copy.deepcopy(saved)

        async def async_save(self, value):
            nonlocal saved
            saved = copy.deepcopy(value)

    monkeypatch.setattr(hub_manager_module, "Store", FakeStore)

    manager = MultiHubManager(FakeHass())
    await manager.async_record_tag_event(TAG.lower(), "BUTTON1", 100.5)
    await manager.async_record_tag_event(TAG, "BUTTON1", 101.5)
    await manager.async_record_tag_event(TAG, "NFC", 102.5)

    assert manager.get_tag_event_stats(TAG) == {
        "BUTTON1": {"count": 2, "last": 101.5},
        "NFC": {"count": 1, "last": 102.5},
    }

    restored = MultiHubManager(FakeHass())
    await restored.async_load_tag_events()
    await restored.async_reset_tag_event_count(TAG, "BUTTON1")

    assert restored.get_tag_event_stats(TAG)["BUTTON1"] == {
        "count": 0,
        "last": 101.5,
    }

    sensor_data = {"event_stats": manager.get_tag_event_stats(TAG)}
    assert _tag_event_count(sensor_data, "BUTTON1") == 2
    assert _tag_event_count(sensor_data, "BUTTON2") == 0
    assert _tag_event_last(sensor_data, "BUTTON1").timestamp() == 101.5
    assert _tag_event_last(sensor_data, "BUTTON2") is None


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


def test_external_duplicate_cannot_own_tag_entities(monkeypatch) -> None:
    manager = MultiHubManager(FakeHass())
    external_hub = FakeHub(
        "entry-external",
        "192.0.2.143",
        last_seen=400,
        is_external=True,
    )
    manager.register_hub(external_hub)

    assert not manager.is_tag_entity_owner("entry-external", TAG)


@pytest.mark.asyncio
async def test_external_only_tag_removes_existing_registry_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FakeEntry("entry-external")
    hass = FakeHass([entry])
    manager = MultiHubManager(hass)
    manager.register_hub(
        FakeHub(
            entry.entry_id,
            "192.0.2.143",
            last_seen=400,
            is_external=True,
        )
    )
    entity = SimpleNamespace(
        entity_id="sensor.test_tag_battery",
        platform="open_epaper_link",
        unique_id=f"{TAG}_battery_percentage",
    )
    ap_entity = SimpleNamespace(
        entity_id="sensor.open_epaper_link_ip",
        platform="open_epaper_link",
        unique_id="ap_ip",
    )
    entity_registry = SimpleNamespace(
        entities={
            entity.entity_id: entity,
            ap_entity.entity_id: ap_entity,
        },
        async_remove=MagicMock(),
    )
    device = SimpleNamespace(
        id="device-tag",
        identifiers={("open_epaper_link", TAG)},
    )
    legacy_ap_device = SimpleNamespace(
        id="device-legacy-ap",
        identifiers={
            ("open_epaper_link", "ap"),
            ("foreign", "unexpected", "identifier", "shape"),
        },
    )
    device_registry = SimpleNamespace(
        devices={
            device.id: device,
            legacy_ap_device.id: legacy_ap_device,
        },
        async_get_device=lambda **kwargs: (
            device
            if kwargs.get("identifiers") == {("open_epaper_link", TAG)}
            else None
        ),
        async_remove_device=MagicMock(),
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.er.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.dr.async_get",
        lambda _hass: device_registry,
    )

    assert await manager.async_reconcile_all_tag_visibility()
    entity_registry.async_remove.assert_called_once_with(entity.entity_id)
    device_registry.async_remove_device.assert_called_once_with(device.id)


@pytest.mark.asyncio
async def test_external_cleanup_waits_for_unloaded_ap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_entry = FakeEntry("entry-external")
    local_entry = FakeEntry("entry-local")
    hass = FakeHass([external_entry, local_entry])
    manager = MultiHubManager(hass)
    manager.register_hub(
        FakeHub(
            external_entry.entry_id,
            "192.0.2.143",
            last_seen=400,
            is_external=True,
        )
    )
    remove_registry_entries = MagicMock()
    monkeypatch.setattr(
        manager, "_remove_tag_registry_entries", remove_registry_entries
    )

    assert not await manager.async_reconcile_tag_visibility(TAG)
    remove_registry_entries.assert_not_called()


@pytest.mark.asyncio
async def test_external_tag_becomes_visible_when_local_ap_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_entry = FakeEntry("entry-external")
    local_entry = FakeEntry("entry-local")
    hass = FakeHass([external_entry, local_entry])
    manager = MultiHubManager(hass)
    manager.register_hub(
        FakeHub(
            external_entry.entry_id,
            "192.0.2.143",
            last_seen=400,
            is_external=True,
        )
    )
    assert not await manager.async_reconcile_tag_visibility(TAG)

    local_hub = FakeHub(
        local_entry.entry_id,
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    manager.register_hub(local_hub)
    migrate_owner = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(manager, "_migrate_tag_registry_owner", migrate_owner)
    monkeypatch.setattr(hub_manager_module, "async_dispatcher_send", dispatch)

    assert await manager.async_reconcile_tag_visibility(TAG)
    assert manager.is_tag_entity_owner(local_entry.entry_id, TAG)
    dispatch.assert_called_once_with(
        hass, "open_epaper_link_tag_discovered", TAG
    )


@pytest.mark.asyncio
async def test_local_tag_becoming_external_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FakeEntry("entry-local")
    hass = FakeHass([entry])
    manager = MultiHubManager(hass)
    hub = FakeHub(
        entry.entry_id,
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    manager.register_hub(hub)
    monkeypatch.setattr(manager, "_migrate_tag_registry_owner", MagicMock())
    assert manager.is_tag_entity_owner(entry.entry_id, TAG)

    hub._data[TAG]["is_external"] = True
    remove_registry_entries = MagicMock()
    monkeypatch.setattr(
        manager, "_remove_tag_registry_entries", remove_registry_entries
    )

    assert not await manager.async_reconcile_tag_visibility(TAG)
    remove_registry_entries.assert_called_once_with(TAG)


def test_stale_entity_registry_owner_moves_to_local_ap(monkeypatch) -> None:
    hass = FakeHass()
    manager = MultiHubManager(hass)
    external_hub = FakeHub(
        "entry-external",
        "192.0.2.143",
        last_seen=400,
        is_external=True,
    )
    local_hub = FakeHub(
        "entry-local",
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    entity = SimpleNamespace(
        entity_id="sensor.test_tag_battery",
        platform="open_epaper_link",
        unique_id=f"{TAG}_battery_percentage",
        config_entry_id="entry-external",
        device_id="device-tag",
    )
    def update_entity(_entity_id, *, config_entry_id):
        entity.config_entry_id = config_entry_id

    entity_registry = SimpleNamespace(
        entities={entity.entity_id: entity},
        async_update_entity=MagicMock(side_effect=update_entity),
    )
    device = SimpleNamespace(
        id="device-tag",
        config_entries={"entry-external"},
    )
    device_registry = SimpleNamespace(
        async_get=lambda device_id: device if device_id == device.id else None,
        async_get_device=lambda **_kwargs: device,
        async_update_device=MagicMock(),
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.er.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.dr.async_get",
        lambda _hass: device_registry,
    )
    manager.register_hub(external_hub)
    manager.register_hub(local_hub)

    assert manager.is_tag_entity_owner("entry-local", TAG)
    assert not manager.is_tag_entity_owner("entry-external", TAG)
    entity_registry.async_update_entity.assert_called_once_with(
        entity.entity_id,
        config_entry_id="entry-local",
    )
    assert device_registry.async_update_device.call_args_list == [
        ((device.id,), {"add_config_entry_id": "entry-local"}),
        ((device.id,), {"remove_config_entry_id": "entry-external"}),
    ]


def test_stale_device_link_is_removed_when_entities_already_have_local_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MultiHubManager(FakeHass())
    external_hub = FakeHub(
        "entry-external",
        "192.0.2.143",
        last_seen=400,
        is_external=True,
    )
    local_hub = FakeHub(
        "entry-local",
        "192.0.2.166",
        last_seen=300,
        is_external=False,
    )
    entity = SimpleNamespace(
        entity_id="sensor.test_tag_battery",
        platform="open_epaper_link",
        unique_id=f"{TAG}_battery_percentage",
        config_entry_id="entry-local",
        device_id="device-tag",
    )
    entity_registry = SimpleNamespace(
        entities={entity.entity_id: entity},
        async_update_entity=MagicMock(),
    )
    device = SimpleNamespace(
        id="device-tag",
        config_entries={"entry-external", "entry-local"},
    )
    device_registry = SimpleNamespace(
        async_get=lambda device_id: device if device_id == device.id else None,
        async_get_device=lambda **_kwargs: device,
        async_update_device=MagicMock(),
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.er.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "custom_components.open_epaper_link.hub_manager.dr.async_get",
        lambda _hass: device_registry,
    )
    manager.register_hub(external_hub)
    manager.register_hub(local_hub)

    assert manager.is_tag_entity_owner("entry-local", TAG)
    entity_registry.async_update_entity.assert_not_called()
    device_registry.async_update_device.assert_called_once_with(
        device.id,
        remove_config_entry_id="entry-external",
    )


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


def test_external_tag_keeps_reported_battery_telemetry() -> None:
    """A replicated AP record may still contain valid battery telemetry."""
    assert _tag_has_battery({"is_external": True, "battery_mv": 3150})


def test_tag_without_battery_telemetry_has_no_battery_entities() -> None:
    assert not _tag_has_battery({"is_external": True, "battery_mv": 0})


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


@pytest.mark.asyncio
async def test_tag_reboot_reasons_emit_once_and_external_records_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only distinct local boot events request cached-image recovery."""
    events = []
    fake_hass = SimpleNamespace(
        bus=SimpleNamespace(async_fire=lambda *args, **kwargs: None),
        data={},
    )
    entry = SimpleNamespace(
        entry_id="entry-a",
        data={"host": "192.0.2.166"},
        options={},
    )

    class FakeStore:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_args, **_kwargs):
            pass

    class FakeDeviceRegistry:
        def async_get_device(self, **_kwargs):
            return None

    monkeypatch.setattr(coordinator, "Store", FakeStore)
    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda _hass: object())
    monkeypatch.setattr(coordinator.dr, "async_get", lambda _hass: FakeDeviceRegistry())
    monkeypatch.setattr(
        coordinator,
        "async_dispatcher_send",
        lambda _hass, signal, *args: events.append((signal, args)),
    )

    hub = coordinator.Hub(fake_hass, entry)
    hub._tag_manager = SimpleNamespace(get_hw_dimensions=lambda _hw: (296, 128))
    hub._known_tags = {TAG}
    hub._data[TAG] = {
        "tag_name": "Test tag",
        "last_seen": 90,
        "runtime": 0,
        "boot_count": 1,
        "checkin_count": 0,
        "block_requests": 0,
    }

    def tag_update(reason, last_seen, update_count, *, external=False):
        return {
            "mac": TAG,
            "alias": "Test tag",
            "lastseen": last_seen,
            "wakeupReason": reason,
            "updatecount": update_count,
            "isexternal": external,
            "hwType": 1,
        }

    await hub._process_tag_data(
        TAG, tag_update(1, 95, 0), is_initial_load=True
    )
    await hub._process_tag_data(TAG, tag_update(1, 100, 1))
    await hub._process_tag_data(TAG, tag_update(1, 100, 1))
    await hub._process_tag_data(TAG, tag_update(252, 110, 2))
    await hub._process_tag_data(TAG, tag_update(254, 120, 3))
    await hub._process_tag_data(TAG, tag_update(0, 130, 4))
    await hub._process_tag_data(
        TAG, tag_update(254, 140, 5, external=True)
    )

    reboot_events = [event for event in events if event[0] == SIGNAL_TAG_REBOOT]
    assert reboot_events == [
        (SIGNAL_TAG_REBOOT, (TAG, "BOOT")),
        (SIGNAL_TAG_REBOOT, (TAG, "FIRSTBOOT")),
        (SIGNAL_TAG_REBOOT, (TAG, "WDT_RESET")),
    ]
    assert hub.get_tag_data(TAG)["boot_count"] == 4


@pytest.mark.asyncio
async def test_button_and_nfc_events_update_stats_once_and_ignore_external_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted local events update HA values and still fire device events."""
    bus_events = []
    recorded = []
    fake_hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_fire=lambda event_type, data: bus_events.append(
                (event_type, data)
            )
        ),
        data={},
    )
    entry = SimpleNamespace(
        entry_id="entry-a",
        data={"host": "192.0.2.166"},
        options={},
    )

    class FakeStore:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_args, **_kwargs):
            pass

    class FakeDeviceRegistry:
        def async_get_device(self, **_kwargs):
            return SimpleNamespace(id="device-a")

    class FakeEventManager:
        async def async_record_tag_event(self, tag_mac, event_type, occurred_at):
            recorded.append((tag_mac, event_type, occurred_at))

        def is_hub_registered(self, _entry_id):
            return False

    monkeypatch.setattr(coordinator, "Store", FakeStore)
    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda _hass: object())
    monkeypatch.setattr(coordinator.dr, "async_get", lambda _hass: FakeDeviceRegistry())
    monkeypatch.setattr(
        coordinator, "get_hub_manager", lambda _hass: FakeEventManager()
    )
    monkeypatch.setattr(
        coordinator, "async_dispatcher_send", lambda *_args, **_kwargs: None
    )

    hub = coordinator.Hub(fake_hass, entry)
    hub._tag_manager = SimpleNamespace(get_hw_dimensions=lambda _hw: (296, 128))

    def tag_update(reason, last_seen, *, external=False):
        return {
            "mac": TAG,
            "alias": "Test tag",
            "lastseen": last_seen,
            "wakeupReason": reason,
            "updatecount": last_seen,
            "isexternal": external,
            "hwType": 1,
        }

    await hub._process_tag_data(
        TAG, tag_update(0, 90), is_initial_load=True
    )
    await hub._process_tag_data(TAG, tag_update(4, 100))
    await hub._process_tag_data(TAG, tag_update(4, 101))
    await hub._process_tag_data(TAG, tag_update(5, 110))
    await hub._process_tag_data(TAG, tag_update(3, 120))
    await hub._process_tag_data(TAG, tag_update(3, 130, external=True))

    assert [(tag, event) for tag, event, _when in recorded] == [
        (TAG, "BUTTON1"),
        (TAG, "BUTTON2"),
        (TAG, "NFC"),
    ]
    assert bus_events == [
        ("open_epaper_link_event", {"device_id": "device-a", "type": "BUTTON1"}),
        ("open_epaper_link_event", {"device_id": "device-a", "type": "BUTTON2"}),
        ("open_epaper_link_event", {"device_id": "device-a", "type": "NFC"}),
    ]
