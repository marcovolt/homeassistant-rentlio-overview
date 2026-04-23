from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .api import RentlioApiClient, RentlioApiError
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
)


class RentlioOverviewConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._setup_data: dict[str, Any] = {}
        self._property_options: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                api = RentlioApiClient(user_input[CONF_API_KEY])
                properties = await api.validate(self.hass)
                if not properties:
                    errors["base"] = "no_properties"
                else:
                    self._setup_data = {
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        CONF_LOOKBACK_DAYS: user_input[CONF_LOOKBACK_DAYS],
                        CONF_LOOKAHEAD_DAYS: user_input[CONF_LOOKAHEAD_DAYS],
                    }
                    if len(properties) == 1:
                        prop = properties[0]
                        property_id = int(prop["id"])
                        await self.async_set_unique_id(f"{DOMAIN}_{property_id}")
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=str(prop.get("name") or "Rentlio Overview"),
                            data={
                                **self._setup_data,
                                CONF_PROPERTY_ID: property_id,
                            },
                        )

                    self._property_options = {str(p["id"]): str(p.get("name") or p["id"]) for p in properties if "id" in p}
                    return await self.async_step_property()
            except RentlioApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
                    vol.Optional(CONF_LOOKBACK_DAYS, default=DEFAULT_LOOKBACK_DAYS): int,
                    vol.Optional(CONF_LOOKAHEAD_DAYS, default=DEFAULT_LOOKAHEAD_DAYS): int,
                }
            ),
            errors=errors,
        )

    async def async_step_property(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                property_id = int(user_input[CONF_PROPERTY_ID])
                await self.async_set_unique_id(f"{DOMAIN}_{property_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._property_options.get(str(property_id), "Rentlio Overview"),
                    data={
                        **self._setup_data,
                        CONF_PROPERTY_ID: property_id,
                    },
                )
            except ValueError:
                errors[CONF_PROPERTY_ID] = "invalid_property_id"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="property",
            data_schema=vol.Schema(
                {vol.Required(CONF_PROPERTY_ID): vol.In(self._property_options)}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return RentlioOverviewOptionsFlow(config_entry)


class RentlioOverviewOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                property_id = int(user_input[CONF_PROPERTY_ID])
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_PROPERTY_ID: property_id,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        CONF_LOOKBACK_DAYS: user_input[CONF_LOOKBACK_DAYS],
                        CONF_LOOKAHEAD_DAYS: user_input[CONF_LOOKAHEAD_DAYS],
                    },
                )
            except ValueError:
                errors[CONF_PROPERTY_ID] = "invalid_property_id"

        current_property_id = self.config_entry.options.get(CONF_PROPERTY_ID, self.config_entry.data.get(CONF_PROPERTY_ID, ""))
        current_scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        current_lookback_days = self.config_entry.options.get(CONF_LOOKBACK_DAYS, self.config_entry.data.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS))
        current_lookahead_days = self.config_entry.options.get(CONF_LOOKAHEAD_DAYS, self.config_entry.data.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROPERTY_ID, default=current_property_id): int,
                    vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval): int,
                    vol.Optional(CONF_LOOKBACK_DAYS, default=current_lookback_days): int,
                    vol.Optional(CONF_LOOKAHEAD_DAYS, default=current_lookahead_days): int,
                }
            ),
            errors=errors,
        )
