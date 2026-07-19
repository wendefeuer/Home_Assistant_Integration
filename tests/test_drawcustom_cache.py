"""Tests for drawcustom upload deduplication."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.open_epaper_link import drawcustom_cache, services
from custom_components.open_epaper_link.const import DOMAIN, SIGNAL_TAG_REBOOT
from custom_components.open_epaper_link.drawcustom_cache import (
    DrawCustomUploadCache,
    ReplayPayload,
    STORAGE_KEY,
    build_upload_fingerprint,
    get_drawcustom_cache,
)
from custom_components.open_epaper_link.upload import UploadQueueHandler
from custom_components.open_epaper_link.switch import (
    TagResendImageAfterRebootSwitch,
)

TAG = "0011223344556677"
ENTITY_ID = f"{DOMAIN}.{TAG.lower()}"


class FakeStore:
    """Small in-memory replacement for Home Assistant Store."""

    saved: dict[str, dict] = {}

    def __init__(self, hass, version, key, **kwargs) -> None:
        self.key = key

    async def async_load(self):
        return deepcopy(self.saved.get(self.key))

    async def async_save(self, data) -> None:
        self.saved[self.key] = deepcopy(data)


class ImmediateQueue:
    """Execute queued work immediately while exposing queue call count."""

    def __init__(self) -> None:
        self.calls = 0

    async def add_to_queue(self, upload_func, *args, **kwargs) -> None:
        self.calls += 1
        await upload_func(*args, **kwargs)

    async def wait_for_current_batch(self):
        return []


class FakeServices:
    def __init__(self) -> None:
        self.handlers = {}

    def async_register(self, domain, name, handler) -> None:
        self.handlers[(domain, name)] = handler


class FakeDeviceRegistry:
    def async_get(self, device_id):
        return SimpleNamespace(identifiers={(DOMAIN, TAG)})


class FakeImageGen:
    image_data = b"rendered-image"

    def __init__(self, hass) -> None:
        pass

    async def get_tag_dimensions(self, entity_id, *, is_ble):
        return 296, 128, "red"

    async def generate_custom_image(self, **kwargs):
        return self.image_data


class FakeHubManager:
    """Expose the active local AP and mutable tag mode for replay tests."""

    def __init__(self) -> None:
        self.hub = SimpleNamespace()
        self.tag_data = {"content_mode": "Home Assistant"}

    def get_tag_data(self, tag_mac):
        return self.tag_data

    def resolve_tag_hub(self, tag_mac, *, require_online=True):
        return self.hub


@pytest.fixture(autouse=True)
def reset_fake_store(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeStore.saved = {}
    monkeypatch.setattr(drawcustom_cache, "Store", FakeStore)


async def _create_drawcustom_handler(
    monkeypatch: pytest.MonkeyPatch,
    upload_mock: AsyncMock,
    *,
    hub_queue=None,
):
    fake_services = FakeServices()
    hass = SimpleNamespace(services=fake_services, data={})
    ble_queue = ImmediateQueue()
    hub_queue = hub_queue or ImmediateQueue()
    dispatcher_handlers = {}
    hub_manager = FakeHubManager()

    monkeypatch.setattr(
        services, "create_upload_queues", lambda: (ble_queue, hub_queue)
    )
    monkeypatch.setattr(services, "ImageGen", FakeImageGen)
    monkeypatch.setattr(services, "is_ble_device", lambda hass, entity_id: False)
    monkeypatch.setattr(
        services,
        "get_hub_for_tag",
        lambda hass, entity_id: hub_manager.hub,
    )
    monkeypatch.setattr(services, "get_hub_manager", lambda hass: hub_manager)
    monkeypatch.setattr(services, "upload_to_hub", upload_mock)
    monkeypatch.setattr(services.dr, "async_get", lambda hass: FakeDeviceRegistry())
    monkeypatch.setattr(services, "async_dispatcher_send", lambda *args: None)
    monkeypatch.setattr(
        services,
        "async_dispatcher_connect",
        lambda hass, signal, handler: dispatcher_handlers.setdefault(signal, handler),
    )

    await services.async_setup_services(hass)
    return (
        fake_services.handlers[(DOMAIN, "drawcustom")],
        hub_queue,
        dispatcher_handlers,
        hass,
        hub_manager,
    )


def _service_call(**data):
    return SimpleNamespace(
        data={
            "device_id": "device-1",
            "payload": [],
            "background": "white",
            **data,
        }
    )


async def test_cache_is_opt_in_and_persists_successful_fingerprint() -> None:
    fingerprint = build_upload_fingerprint(b"image", {"dither": 2})
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()

    first = await cache.async_reserve("ap:tag", fingerprint, only_if_changed=True)
    assert first is not None
    await cache.async_mark_success(first)
    assert (
        await cache.async_reserve("ap:tag", fingerprint, only_if_changed=True)
        is None
    )

    restarted_cache = DrawCustomUploadCache(SimpleNamespace())
    await restarted_cache.async_load()
    assert (
        await restarted_cache.async_reserve(
            "ap:tag", fingerprint, only_if_changed=True
        )
        is None
    )
    assert (
        await restarted_cache.async_reserve(
            "ap:tag", fingerprint, only_if_changed=False
        )
        is not None
    )


async def test_existing_fingerprint_only_store_remains_compatible() -> None:
    fingerprint = build_upload_fingerprint(b"legacy", {})
    FakeStore.saved[STORAGE_KEY] = {
        "fingerprints": {"ap:tag": fingerprint}
    }
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()

    assert (
        await cache.async_reserve("ap:tag", fingerprint, only_if_changed=True)
        is None
    )
    await cache.async_set_resend_enabled("ap:tag", True)
    assert await cache.async_reserve_replay("ap:tag") is None


async def test_failed_upload_can_be_retried() -> None:
    fingerprint = build_upload_fingerprint(b"image", {})
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()

    failed = await cache.async_reserve("ap:tag", fingerprint, only_if_changed=True)
    assert failed is not None
    await cache.async_mark_failure(failed)

    retry = await cache.async_reserve("ap:tag", fingerprint, only_if_changed=True)
    assert retry is not None


async def test_tail_deduplication_preserves_a_b_a_order() -> None:
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()
    fingerprint_a = build_upload_fingerprint(b"a", {})
    fingerprint_b = build_upload_fingerprint(b"b", {})

    first_a = await cache.async_reserve("ap:tag", fingerprint_a, only_if_changed=True)
    assert first_a is not None
    assert (
        await cache.async_reserve("ap:tag", fingerprint_a, only_if_changed=True)
        is None
    )
    assert (
        await cache.async_reserve("ap:tag", fingerprint_b, only_if_changed=True)
        is not None
    )
    last_a = await cache.async_reserve("ap:tag", fingerprint_a, only_if_changed=True)
    assert last_a is not None


async def test_concurrent_identical_reservations_are_deduplicated() -> None:
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()
    fingerprint = build_upload_fingerprint(b"same", {})

    reservations = await asyncio.gather(
        cache.async_reserve("ap:tag", fingerprint, only_if_changed=True),
        cache.async_reserve("ap:tag", fingerprint, only_if_changed=True),
    )

    assert sum(reservation is not None for reservation in reservations) == 1


async def test_displays_and_transports_have_independent_cache_entries() -> None:
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()
    fingerprint = build_upload_fingerprint(b"same", {})

    ap_first = await cache.async_reserve(
        "ap:first", fingerprint, only_if_changed=True
    )
    assert ap_first is not None
    await cache.async_mark_success(ap_first)

    assert (
        await cache.async_reserve("ap:first", fingerprint, only_if_changed=True)
        is None
    )
    assert (
        await cache.async_reserve("ap:second", fingerprint, only_if_changed=True)
        is not None
    )
    assert (
        await cache.async_reserve("ble:first", fingerprint, only_if_changed=True)
        is not None
    )


async def test_replay_payload_and_switch_setting_persist_across_restart() -> None:
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()
    parameters = {"dither": 2, "ttl_minutes": 5, "lut": 1}
    fingerprint = build_upload_fingerprint(b"image", parameters)
    payload = ReplayPayload(b"image", parameters, fingerprint)

    reservation = await cache.async_reserve(
        "ap:first", fingerprint, only_if_changed=False
    )
    assert reservation is not None
    await cache.async_mark_success(reservation, payload)
    await cache.async_set_resend_enabled("ap:first", True)

    restarted_cache = DrawCustomUploadCache(SimpleNamespace())
    await restarted_cache.async_load()
    assert restarted_cache.is_resend_enabled("ap:first")
    assert not restarted_cache.is_resend_enabled("ap:second")
    replay = await restarted_cache.async_reserve_replay("ap:first")
    assert replay is not None
    assert replay[1] == payload


async def test_reboot_replay_switch_is_visible_off_and_persistent() -> None:
    first_hass = SimpleNamespace(data={})
    first_cache = get_drawcustom_cache(first_hass)
    await first_cache.async_load()
    first_entity = TagResendImageAfterRebootSwitch(
        SimpleNamespace(hass=first_hass), TAG
    )
    first_entity.async_write_ha_state = lambda: None

    assert first_entity._attr_entity_registry_enabled_default
    assert first_entity._attr_unique_id == f"{TAG}_resend_image_after_reboot"
    assert first_entity.is_on is False
    await first_entity.async_turn_on()
    assert first_entity.is_on is True

    restarted_hass = SimpleNamespace(data={})
    restarted_cache = get_drawcustom_cache(restarted_hass)
    await restarted_cache.async_load()
    restarted_entity = TagResendImageAfterRebootSwitch(
        SimpleNamespace(hass=restarted_hass), TAG
    )
    assert restarted_entity.is_on is True


async def test_replay_is_blocked_while_newer_upload_is_pending() -> None:
    cache = DrawCustomUploadCache(SimpleNamespace())
    await cache.async_load()
    fingerprint_a = build_upload_fingerprint(b"a", {})
    payload_a = ReplayPayload(b"a", {}, fingerprint_a)
    first = await cache.async_reserve(
        "ap:first", fingerprint_a, only_if_changed=False
    )
    assert first is not None
    await cache.async_mark_success(first, payload_a)
    await cache.async_set_resend_enabled("ap:first", True)

    pending = await cache.async_reserve(
        "ap:first", build_upload_fingerprint(b"b", {}), only_if_changed=False
    )
    assert pending is not None
    assert await cache.async_reserve_replay("ap:first") is None

    await cache.async_mark_failure(pending)
    assert await cache.async_reserve_replay("ap:first") is not None


async def test_fingerprints_include_effective_upload_parameters() -> None:
    image = b"same-image"
    first = build_upload_fingerprint(image, {"dither": 2, "ttl_minutes": 1})
    assert first == build_upload_fingerprint(image, {"ttl_minutes": 1, "dither": 2})
    assert first != build_upload_fingerprint(image, {"dither": 1, "ttl_minutes": 1})
    assert first != build_upload_fingerprint(
        b"changed-image", {"dither": 2, "ttl_minutes": 1}
    )


async def test_drawcustom_skips_unchanged_opt_in_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock()
    handler, queue, _, _, _ = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )

    await handler(_service_call(only_if_changed=True))
    await handler(_service_call(only_if_changed=True))

    assert queue.calls == 1
    assert upload_mock.await_count == 1


async def test_drawcustom_default_always_uploads_and_changed_settings_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock()
    handler, queue, _, _, _ = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )

    await handler(_service_call())
    await handler(_service_call())
    await handler(_service_call(only_if_changed=True, dither=1))

    assert queue.calls == 3
    assert upload_mock.await_count == 3


async def test_drawcustom_dry_run_does_not_seed_upload_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock()
    handler, queue, _, _, _ = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )

    await handler(_service_call(**{"dry-run": True}, only_if_changed=True))
    await handler(_service_call(only_if_changed=True))

    assert queue.calls == 1
    assert upload_mock.await_count == 1


async def test_drawcustom_upload_failure_does_not_seed_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock(
        side_effect=[HomeAssistantError("first upload failed"), None]
    )
    handler, queue, _, _, _ = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )

    with pytest.raises(HomeAssistantError):
        await handler(_service_call(only_if_changed=True))
    await handler(_service_call(only_if_changed=True))

    assert queue.calls == 2
    assert upload_mock.await_count == 2


async def test_enabled_reboot_replays_last_successful_ap_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock()
    handler, queue, dispatchers, hass, _ = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )
    await handler(_service_call(ttl=300, dither=1, refresh_type=2))
    cache = get_drawcustom_cache(hass)
    await cache.async_set_resend_enabled(f"ap:{TAG}", True)

    await dispatchers[SIGNAL_TAG_REBOOT](TAG, "BOOT")

    assert queue.calls == 2
    assert upload_mock.await_count == 2
    replay_args = upload_mock.await_args_list[1].args
    assert replay_args[2] == FakeImageGen.image_data
    assert replay_args[3:] == (1, 300, 0, 0, 2)


async def test_reboot_replay_skips_disabled_missing_and_non_ha_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_mock = AsyncMock()
    handler, queue, dispatchers, hass, manager = await _create_drawcustom_handler(
        monkeypatch, upload_mock
    )

    await dispatchers[SIGNAL_TAG_REBOOT](TAG, "FIRSTBOOT")
    assert queue.calls == 0

    await handler(_service_call())
    await dispatchers[SIGNAL_TAG_REBOOT](TAG, "WDT_RESET")
    assert queue.calls == 1

    cache = get_drawcustom_cache(hass)
    await cache.async_set_resend_enabled(f"ap:{TAG}", True)
    manager.tag_data["content_mode"] = "Timestamp"
    await dispatchers[SIGNAL_TAG_REBOOT](TAG, "BOOT")
    assert queue.calls == 1


async def test_upload_queue_respects_max_concurrent_limit() -> None:
    queue = UploadQueueHandler(max_concurrent=1, cooldown=0)
    active = 0
    maximum_active = 0

    async def upload(entity_id):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1

    await queue.add_to_queue(upload, ENTITY_ID)
    await queue.add_to_queue(upload, ENTITY_ID)
    await queue.wait_for_current_batch()

    assert maximum_active == 1
