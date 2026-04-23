from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import RentlioApiClient
from .const import (
    CONF_API_KEY,
    CONF_LOOKAHEAD_DAYS,
    CONF_LOOKBACK_DAYS,
    CONF_PROPERTY_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import RentlioCoordinator



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = RentlioApiClient(entry.data[CONF_API_KEY])
    property_id = entry.options.get(CONF_PROPERTY_ID, entry.data[CONF_PROPERTY_ID])
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    lookback_days = entry.options.get(CONF_LOOKBACK_DAYS, entry.data.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS))
    lookahead_days = entry.options.get(CONF_LOOKAHEAD_DAYS, entry.data.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS))

    coordinator = RentlioCoordinator(
        hass,
        api,
        property_id=property_id,
        scan_interval_seconds=scan_interval,
        lookback_days=lookback_days,
        lookahead_days=lookahead_days,
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
