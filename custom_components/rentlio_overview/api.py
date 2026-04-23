from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlencode

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class RentlioApiError(Exception):
    """Rentlio API error."""


class RentlioApiClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def _get(self, hass, path: str, params: dict[str, Any] | None = None) -> Any:
        session = async_get_clientsession(hass)
        query = {"apikey": self._api_key}
        if params:
            query.update({k: v for k, v in params.items() if v is not None and v != ""})
        url = f"{API_BASE}{path}?{urlencode(query, doseq=True)}"
        _LOGGER.debug("Rentlio GET %s", url.replace(self._api_key, "***"))
        async with asyncio.timeout(30):
            resp = await session.get(url)
            text = await resp.text()
        if resp.status >= 400:
            raise RentlioApiError(f"HTTP {resp.status}: {text}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise RentlioApiError(f"Invalid JSON from API: {text[:300]}") from err

    async def validate(self, hass) -> list[dict[str, Any]]:
        payload = await self._get(hass, "/properties")
        return list(payload.get("data", []))

    async def get_properties(self, hass) -> list[dict[str, Any]]:
        payload = await self._get(hass, "/properties")
        return list(payload.get("data", []))

    async def get_units(self, hass, property_id: int | str) -> list[dict[str, Any]]:
        payload = await self._get(hass, f"/properties/{property_id}/units")
        return list(payload.get("data", []))

    async def get_sales_channels(self, hass, property_id: int | str) -> list[dict[str, Any]]:
        payload = await self._get(hass, f"/properties/{property_id}/sales-channels")
        return list(payload.get("data", []))

    async def get_reservations_for_unit(
        self,
        hass,
        unit_id: int | str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        per_page = 100
        page = 1
        collected: list[dict[str, Any]] = []
        total_expected: int | None = None
        while True:
            payload = await self._get(
                hass,
                "/reservations",
                params={
                    "order_by": "arrivalDate",
                    "status": 1,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "unitsId": unit_id,
                    "perPage": per_page,
                    "page": page,
                },
            )
            rows: list[dict[str, Any]] = []
            if "data" in payload and isinstance(payload["data"], list):
                rows = list(payload["data"])
            elif "reservations" in payload and isinstance(payload["reservations"], list):
                rows = list(payload["reservations"])
            collected.extend(rows)
            if total_expected is None:
                total_raw = payload.get("total")
                try:
                    total_expected = int(total_raw) if total_raw not in (None, "") else None
                except (TypeError, ValueError):
                    total_expected = None
            if not rows:
                break
            if total_expected is not None and len(collected) >= total_expected:
                break
            if len(rows) < per_page:
                break
            page += 1
        return collected
