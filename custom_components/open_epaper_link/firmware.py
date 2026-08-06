"""Firmware release discovery for OpenEPaperLink access points."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Final

import aiohttp
import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER: Final = logging.getLogger(__name__)

DEFAULT_FIRMWARE_REPOSITORY = "OpenEPaperLink/OpenEPaperLink"
FIRMWARE_RELEASE_CACHE_TTL = timedelta(hours=6)
FIRMWARE_RELEASE_CACHE_KEY = "firmware_release_cache"
FIRMWARE_RELEASE_LOCKS_KEY = "firmware_release_locks"
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class FirmwareRelease:
    """Metadata for one stable OpenEPaperLink firmware release."""

    version: str
    published_at: datetime | None
    release_url: str
    asset_names: frozenset[str]

    def supports_environment(self, environment: str | None) -> bool:
        """Return whether the release contains the AP's firmware binary."""
        return bool(environment) and f"{environment}.bin" in self.asset_names


@dataclass(frozen=True, slots=True)
class CachedFirmwareRelease:
    """A GitHub lookup result with its fetch timestamp."""

    release: FirmwareRelease | None
    fetched_at: datetime


def normalize_repository(repository: object) -> str | None:
    """Return a safe GitHub owner/repository value."""
    if not isinstance(repository, str):
        return None
    repository = repository.strip()
    return repository if _REPOSITORY_PATTERN.fullmatch(repository) else None


def parse_github_release(data: object) -> FirmwareRelease | None:
    """Validate and convert a GitHub latest-release response."""
    if not isinstance(data, dict):
        return None

    version = data.get("tag_name")
    release_url = data.get("html_url")
    assets = data.get("assets")
    if not isinstance(version, str) or not version:
        return None
    if not isinstance(release_url, str) or not release_url:
        return None
    if not isinstance(assets, list):
        return None

    asset_names = frozenset(
        asset["name"]
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and asset["name"]
    )

    published_at = None
    raw_published_at = data.get("published_at")
    if isinstance(raw_published_at, str):
        try:
            published_at = datetime.fromisoformat(
                raw_published_at.replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return FirmwareRelease(
        version=version,
        published_at=published_at,
        release_url=release_url,
        asset_names=asset_names,
    )


async def async_get_latest_firmware_release(
    hass: HomeAssistant,
    repository: object,
    environment: str | None,
) -> FirmwareRelease | None:
    """Return a cached stable release when it supports the AP environment."""
    normalized_repository = normalize_repository(repository)
    if normalized_repository is None:
        _LOGGER.warning("Ignoring invalid firmware repository: %r", repository)
        return None

    domain_data = hass.data.setdefault(DOMAIN, {})
    cache: dict[str, CachedFirmwareRelease] = domain_data.setdefault(
        FIRMWARE_RELEASE_CACHE_KEY, {}
    )
    locks: dict[str, asyncio.Lock] = domain_data.setdefault(
        FIRMWARE_RELEASE_LOCKS_KEY, {}
    )
    lock = locks.setdefault(normalized_repository, asyncio.Lock())

    async with lock:
        now = datetime.now(timezone.utc)
        cached = cache.get(normalized_repository)
        if cached and now - cached.fetched_at < FIRMWARE_RELEASE_CACHE_TTL:
            return (
                cached.release
                if cached.release is not None
                and cached.release.supports_environment(environment)
                else None
            )

        url = f"https://api.github.com/repos/{normalized_repository}/releases/latest"
        session = async_get_clientsession(hass)
        try:
            async with async_timeout.timeout(10):
                async with session.get(
                    url,
                    headers={"Accept": "application/vnd.github+json"},
                ) as response:
                    response.raise_for_status()
                    release = parse_github_release(await response.json())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as err:
            cache[normalized_repository] = CachedFirmwareRelease(None, now)
            _LOGGER.warning(
                "Unable to check firmware release for %s: %s",
                normalized_repository,
                err,
            )
            return None

        if release is None:
            cache[normalized_repository] = CachedFirmwareRelease(None, now)
            _LOGGER.warning(
                "GitHub returned invalid firmware release data for %s",
                normalized_repository,
            )
            return None

        cache[normalized_repository] = CachedFirmwareRelease(release, now)
        return release if release.supports_environment(environment) else None
