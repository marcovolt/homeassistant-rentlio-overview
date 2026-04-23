from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    RentlioCoordinator,
    UnitState,
    enrich_reservation,
    reservation_net_total,
    reservation_nights,
    ts_to_date,
)


def _safe_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _calendar_total_price(reservation: dict[str, Any]) -> float:
    return reservation_net_total(reservation)


def _calendar_daily_average(reservation: dict[str, Any]) -> float | None:
    nights = reservation_nights(reservation)
    if not nights:
        return None
    return round(_calendar_total_price(reservation) / nights, 2)


def _channel_summary(reservation: dict[str, Any]) -> str:
    return str(
        reservation.get("_channel_name")
        or reservation.get("salesChannelName")
        or reservation.get("otaChannelName")
        or "Direct Booking"
    )


def _reservation_description(reservation: dict[str, Any], unit_name: str, include_unit: bool = True) -> str:
    total_price = _calendar_total_price(reservation)
    daily_average = _calendar_daily_average(reservation)
    nights = reservation_nights(reservation)
    parts = []
    if include_unit:
        parts.append(f"Unit: {unit_name}")
    parts.append(f"Net reservation total: {total_price:.2f} €")
    if daily_average is not None:
        parts.append(f"Net average per night: {daily_average:.2f} €")
    if nights is not None:
        parts.append(f"Total nights: {nights}")
    return "\n".join(parts)


def _reservation_to_event(reservation: dict[str, Any], unit_name: str, include_unit: bool = True) -> CalendarEvent | None:
    arrival = ts_to_date(reservation.get("arrivalDate"))
    departure = ts_to_date(reservation.get("departureDate"))
    if arrival is None or departure is None or departure <= arrival:
        return None

    return CalendarEvent(
        start=arrival,
        end=departure,
        summary=_channel_summary(reservation),
        location=unit_name,
        description=_reservation_description(reservation, unit_name, include_unit=include_unit),
        uid=f"rentlio-{unit_name}-{reservation.get('id')}",
    )


def _reservation_overlaps_range(reservation: dict[str, Any], start_date: datetime, end_date: datetime) -> bool:
    arrival = ts_to_date(reservation.get("arrivalDate"))
    departure = ts_to_date(reservation.get("departureDate"))
    if arrival is None or departure is None:
        return False
    request_start = start_date.date()
    request_end = end_date.date()
    return departure > request_start and arrival < request_end


def _sort_reservations(reservations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        reservations,
        key=lambda reservation: (
            ts_to_date(reservation.get("arrivalDate")) or date.max,
            ts_to_date(reservation.get("departureDate")) or date.max,
            int(reservation.get("id", 0) or 0),
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RentlioCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RentlioCalendarEntity] = [
        RentlioCalendarEntity(
            coordinator,
            entry,
            calendar_key="property",
            name="Property Bookings",
            unit_key=None,
        )
    ]

    for unit_key in coordinator.data.get("units", {}):
        unit = coordinator.data["units"][unit_key]
        entities.append(
            RentlioCalendarEntity(
                coordinator,
                entry,
                calendar_key=f"unit_{unit.unit_id or unit_key}",
                name=f"{unit.unit_name} Bookings",
                unit_key=unit_key,
            )
        )

    async_add_entities(entities)


class RentlioCalendarEntity(CoordinatorEntity[RentlioCoordinator], CalendarEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RentlioCoordinator,
        entry: ConfigEntry,
        *,
        calendar_key: str,
        name: str,
        unit_key: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._unit_key = unit_key
        self._attr_name = name
        self._attr_unique_id = f"rentlio_overview_calendar_{calendar_key}"
        self._attr_icon = "mdi:calendar-month"
        self._event: CalendarEvent | None = None
        self._refresh_current_event()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self._entry.entry_id}_booking_calendars")},
            "name": "Rentlio Booking Calendars",
            "manufacturer": "Rentlio",
            "model": "Booking Calendar",
        }

    @property
    def event(self) -> CalendarEvent | None:
        return self._event

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_current_event()
        super()._handle_coordinator_update()

    def _refresh_current_event(self) -> None:
        self._event = self._select_event_from_cache()

    def _select_event_from_cache(self) -> CalendarEvent | None:
        if self._unit_key is not None:
            unit: UnitState = self.coordinator.data.get("units", {}).get(self._unit_key)
            if not unit:
                return None
            if unit.current_reservation:
                return _reservation_to_event(unit.current_reservation, unit.unit_name, include_unit=False)
            if unit.next_reservation:
                return _reservation_to_event(unit.next_reservation, unit.unit_name, include_unit=False)
            return None

        current_reservations: list[tuple[dict[str, Any], str]] = []
        next_reservations: list[tuple[dict[str, Any], str]] = []
        for unit in self.coordinator.data.get("units", {}).values():
            if unit.current_reservation:
                current_reservations.append((unit.current_reservation, unit.unit_name))
            elif unit.next_reservation:
                next_reservations.append((unit.next_reservation, unit.unit_name))

        if current_reservations:
            reservation, unit_name = min(
                current_reservations,
                key=lambda item: (
                    ts_to_date(item[0].get("departureDate")) or date.max,
                    ts_to_date(item[0].get("arrivalDate")) or date.max,
                ),
            )
            return _reservation_to_event(reservation, unit_name, include_unit=True)

        if next_reservations:
            reservation, unit_name = min(
                next_reservations,
                key=lambda item: (
                    ts_to_date(item[0].get("arrivalDate")) or date.max,
                    ts_to_date(item[0].get("departureDate")) or date.max,
                ),
            )
            return _reservation_to_event(reservation, unit_name, include_unit=True)

        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        reservations_with_unit = await self._async_fetch_reservations(hass, start_date, end_date)
        events: list[CalendarEvent] = []
        include_unit = self._unit_key is None

        for reservation, unit_name in reservations_with_unit:
            if not _reservation_overlaps_range(reservation, start_date, end_date):
                continue
            event = _reservation_to_event(reservation, unit_name, include_unit=include_unit)
            if event is not None:
                events.append(event)

        return sorted(events, key=lambda event: (event.start, event.end, event.summary))

    async def _async_fetch_reservations(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[dict[str, Any], str]]:
        date_from = start_date.date().isoformat()
        date_to = end_date.date().isoformat()
        sales_channels = self.coordinator.data.get("sales_channels", {})

        if self._unit_key is not None:
            unit: UnitState = self.coordinator.data.get("units", {}).get(self._unit_key)
            if not unit or unit.unit_id is None:
                return []
            reservations = await self.coordinator.api.get_reservations_for_unit(hass, unit.unit_id, date_from, date_to)
            normalized = [reservation for reservation in reservations if int(reservation.get("status", 0) or 0) == 1]
            for reservation in normalized:
                enrich_reservation(reservation, sales_channels, start_date.date())
            return [(reservation, unit.unit_name) for reservation in _sort_reservations(normalized)]

        reservations_with_unit: list[tuple[dict[str, Any], str]] = []
        for unit in self.coordinator.data.get("units", {}).values():
            if unit.unit_id is None:
                continue
            reservations = await self.coordinator.api.get_reservations_for_unit(hass, unit.unit_id, date_from, date_to)
            normalized = [reservation for reservation in reservations if int(reservation.get("status", 0) or 0) == 1]
            for reservation in normalized:
                enrich_reservation(reservation, sales_channels, start_date.date())
            reservations_with_unit.extend((reservation, unit.unit_name) for reservation in normalized)

        return sorted(
            reservations_with_unit,
            key=lambda item: (
                ts_to_date(item[0].get("arrivalDate")) or date.max,
                ts_to_date(item[0].get("departureDate")) or date.max,
                item[1],
            ),
        )
