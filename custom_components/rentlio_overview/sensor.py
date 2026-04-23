from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RentlioCoordinator, ts_to_date, ts_to_iso


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attrs.items() if value is not None and value != ""}


def _notes_to_text(notes: list[str]) -> str | None:
    cleaned = [note for note in notes if note]
    return "; ".join(cleaned) if cleaned else None


def _coordinator_today(coordinator: RentlioCoordinator):
    now_value = coordinator.data.get("now")
    if isinstance(now_value, str):
        try:
            return datetime.fromisoformat(now_value).date()
        except ValueError:
            pass
    return datetime.now().date()


def _days_until_arrival(reservation: dict[str, Any] | None, today_date) -> int | None:
    if not reservation:
        return None
    arrival = ts_to_date(reservation.get("arrivalDate"))
    if arrival is None:
        return None
    return (arrival - today_date).days


def _reservation_gap_nights(current_reservation: dict[str, Any] | None, next_reservation: dict[str, Any] | None) -> int | None:
    if not current_reservation or not next_reservation:
        return None

    current_departure = ts_to_date(current_reservation.get("departureDate"))
    next_arrival = ts_to_date(next_reservation.get("arrivalDate"))
    if current_departure is None or next_arrival is None:
        return None

    return (next_arrival - current_departure).days


def _reservation_attrs(
    reservation: dict[str, Any] | None,
    empty_text: str,
    *,
    include_days_until_arrival: bool = False,
    today_date=None,
) -> dict[str, Any]:
    if not reservation:
        return {"reservation": empty_text}

    attrs = {
        "reservation_id": reservation.get("id"),
        "guest_name": reservation.get("guestName"),
        "guest_country": reservation.get("guestCountryName"),
        "arrival": ts_to_iso(reservation.get("arrivalDate")),
        "departure": ts_to_iso(reservation.get("departureDate")),
        "total_nights": reservation.get("_nights"),
        "total_guests": reservation.get("_guest_total"),
        "accommodation_total": reservation.get("_accommodation_total_price"),
        "services_total": reservation.get("totalServicesPrice"),
        "gross_reservation_total": reservation.get("_gross_total_reservation_price"),
        "channel_commission_amount": reservation.get("_channel_commission_total"),
        "channel_commission_rate": reservation.get("channelCommissionPercentage"),
        "net_reservation_total": reservation.get("_net_total_reservation_price"),
        "accommodation_average_per_night": reservation.get("_accommodation_price_per_night"),
        "net_average_per_night": reservation.get("_net_price_per_night"),
        "vat_rate": reservation.get("vatRate"),
        "vat_amount": reservation.get("vatAmount"),
        "vat_included": reservation.get("vatIncluded"),
        "currency_id": reservation.get("currencyId"),
        "is_paid": reservation.get("isPaid"),
        "booked_at": ts_to_iso(reservation.get("bookedAt")),
        "days_since_booking": reservation.get("_days_since_booking"),
        "channel_id": reservation.get("salesChannelsId") or reservation.get("channelId") or reservation.get("channelID"),
        "channel_name": reservation.get("_channel_name"),
        "ota_channel_name": reservation.get("otaChannelName"),
    }
    if include_days_until_arrival and today_date is not None:
        attrs["days_until_arrival"] = _days_until_arrival(reservation, today_date)
    return _clean_attrs(attrs)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RentlioCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        RentlioGlobalDiagnosticSensor(coordinator, entry),
        RentlioOverviewSensor(coordinator, entry),
        RentlioRevenueTodaySensor(coordinator, entry),
        RentlioArrivalsTodaySensor(coordinator, entry),
        RentlioDeparturesTodaySensor(coordinator, entry),
        RentlioTurnoversTodaySensor(coordinator, entry),
        RentlioAnnualGlobalRevenueSensor(coordinator, entry, "elapsed_year", "Elapsed Year Net Revenue"),
        RentlioAnnualGlobalRevenueSensor(coordinator, entry, "remaining_year", "Remaining Year Net Revenue"),
        RentlioAnnualGlobalRevenueSensor(coordinator, entry, "full_year", "Full Year Net Revenue"),
    ]
    for unit_key in coordinator.data.get("units", {}):
        entities.append(RentlioUnitStatusSensor(coordinator, entry, unit_key))
        entities.append(RentlioUnitCurrentReservationStatusSensor(coordinator, entry, unit_key))
        entities.append(RentlioUnitNextReservationStatusSensor(coordinator, entry, unit_key))
        entities.append(RentlioUnitCurrentNetAveragePerNightSensor(coordinator, entry, unit_key))
        entities.append(RentlioAnnualUnitRevenueSensor(coordinator, entry, unit_key, "elapsed_year", "Elapsed Year Net Revenue"))
        entities.append(RentlioAnnualUnitRevenueSensor(coordinator, entry, unit_key, "remaining_year", "Remaining Year Net Revenue"))
        entities.append(RentlioAnnualUnitRevenueSensor(coordinator, entry, unit_key, "full_year", "Full Year Net Revenue"))
    async_add_entities(entities)


class RentlioBase(CoordinatorEntity[RentlioCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RentlioCoordinator,
        entry: ConfigEntry,
        *,
        device_suffix: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_suffix = device_suffix
        self._device_name = device_name
        self._attr_unique_id = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self._entry.entry_id}_{self._device_suffix}")},
            "name": self._device_name,
            "manufacturer": "Rentlio",
            "model": "Reservation Board",
        }


class RentlioPropertyBase(RentlioBase):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            device_suffix="property",
            device_name="Rentlio Property",
        )


class RentlioPropertyAnnualBase(RentlioBase):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            device_suffix="property_annual",
            device_name="Rentlio Property Annual",
        )


class RentlioUnitBase(RentlioBase):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        self.unit_key = unit_key
        unit = coordinator.data["units"][unit_key]
        self._unit_id = unit.unit_id or unit_key
        self._unit_name = unit.unit_name
        super().__init__(
            coordinator,
            entry,
            device_suffix=f"unit_{self._unit_id}",
            device_name=self._unit_name,
        )


class RentlioUnitAnnualBase(RentlioBase):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        self.unit_key = unit_key
        unit = coordinator.data["units"][unit_key]
        self._unit_id = unit.unit_id or unit_key
        self._unit_name = unit.unit_name
        super().__init__(
            coordinator,
            entry,
            device_suffix=f"unit_{self._unit_id}_annual",
            device_name=f"{self._unit_name} Annual",
        )


class RentlioGlobalDiagnosticSensor(RentlioPropertyBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Diagnostic"
        self._attr_unique_id = "rentlio_overview_property_diagnostic"
        self._attr_icon = "mdi:stethoscope"

    @property
    def native_value(self):
        return self.coordinator.data.get("unit_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return _clean_attrs(
            {
                "property_count": data.get("property_count"),
                "unit_count": data.get("unit_count"),
                "reservation_count": data.get("reservation_count"),
                "occupied_units": data.get("occupied_count"),
                "date_from": data.get("date_from"),
                "date_to": data.get("date_to"),
                "timezone": data.get("timezone"),
                "now": data.get("now"),
                "lookback_days": data.get("lookback_days"),
                "lookahead_days": data.get("lookahead_days"),
            }
        )


class RentlioOverviewSensor(RentlioPropertyBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Overview"
        self._attr_unique_id = "rentlio_overview_overview"
        self._attr_icon = "mdi:domain"

    @property
    def native_value(self):
        return self.coordinator.data.get("occupied_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return _clean_attrs(
            {
                "occupied_units": data.get("occupied_count", 0),
                "vacant_units": max(int(data.get("unit_count", 0)) - int(data.get("occupied_count", 0)), 0),
                "guests_staying_today": data.get("current_people_total", 0),
                "arrivals_today": data.get("check_ins_today", 0),
                "departures_today": data.get("check_outs_today", 0),
                "turnovers_today": data.get("turnovers_today", 0),
                "net_revenue_today": data.get("daily_revenue_today", 0),
                "gross_revenue_today": data.get("daily_gross_revenue_today", 0),
                "services_total_today": data.get("daily_services_today", 0),
                "channel_commission_amount_today": data.get("daily_channel_commission_today", 0),
                "vat_amount_today": data.get("daily_vat_today", 0),
                "avg_vat_rate_today": data.get("avg_vat_rate_today"),
                "paid_occupied_units": data.get("paid_present_count", 0),
                "unpaid_occupied_units": data.get("unpaid_present_count", 0),
                "lookback_days": data.get("lookback_days"),
                "lookahead_days": data.get("lookahead_days"),
            }
        )


class RentlioRevenueTodaySensor(RentlioPropertyBase, SensorEntity):
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Revenue Today"
        self._attr_unique_id = "rentlio_overview_revenue_today"
        self._attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self):
        return _float_or_none(self.coordinator.data.get("daily_revenue_today", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return _clean_attrs(
            {
                "occupied_units": data.get("occupied_count", 0),
                "guests_staying_today": data.get("current_people_total", 0),
                "gross_revenue_today": data.get("daily_gross_revenue_today", 0),
                "services_total_today": data.get("daily_services_today", 0),
                "channel_commission_amount_today": data.get("daily_channel_commission_today", 0),
                "vat_amount_today": data.get("daily_vat_today", 0),
                "avg_vat_rate_today": data.get("avg_vat_rate_today"),
                "paid_occupied_units": data.get("paid_present_count", 0),
                "unpaid_occupied_units": data.get("unpaid_present_count", 0),
            }
        )


class RentlioArrivalsTodaySensor(RentlioPropertyBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Arrivals Today"
        self._attr_unique_id = "rentlio_overview_arrivals_today"
        self._attr_icon = "mdi:calendar-arrow-right"

    @property
    def native_value(self):
        return self.coordinator.data.get("check_ins_today", 0)


class RentlioDeparturesTodaySensor(RentlioPropertyBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Departures Today"
        self._attr_unique_id = "rentlio_overview_departures_today"
        self._attr_icon = "mdi:calendar-arrow-left"

    @property
    def native_value(self):
        return self.coordinator.data.get("check_outs_today", 0)


class RentlioTurnoversTodaySensor(RentlioPropertyBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Turnovers Today"
        self._attr_unique_id = "rentlio_overview_turnovers_today"
        self._attr_icon = "mdi:autorenew"

    @property
    def native_value(self):
        return self.coordinator.data.get("turnovers_today", 0)


class RentlioUnitStatusSensor(RentlioUnitBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        super().__init__(coordinator, entry, unit_key)
        self._attr_name = "Status"
        self._attr_unique_id = f"rentlio_overview_unit_{self._unit_id}_reservation_status"

    @property
    def icon(self) -> str:
        state = self.native_value
        icon_map = {
            "vacant": "mdi:door-open",
            "occupied": "mdi:bed",
            "arrival_today": "mdi:calendar-arrow-right",
            "departure_today": "mdi:calendar-arrow-left",
            "turnover_today": "mdi:autorenew",
        }
        return icon_map.get(str(state), "mdi:home-account")

    @property
    def native_value(self):
        unit = self.coordinator.data["units"][self.unit_key]
        return unit.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self.coordinator.data["units"][self.unit_key]
        today_date = _coordinator_today(self.coordinator)
        attrs = {
            "unit_id": unit.unit_id,
            "unit_name": unit.unit_name,
            "property_id": unit.property_id,
            "property_name": unit.property_name,
            "occupied": unit.occupied,
            "has_current_reservation": unit.current_reservation is not None,
            "has_next_reservation": unit.next_reservation is not None,
            "has_arrival_today": unit.has_check_in_today,
            "has_departure_today": unit.has_check_out_today,
            "has_turnover_today": unit.has_turnover_today,
            "reservation_count": len(unit.reservations),
            "days_until_next_reservation": _days_until_arrival(unit.next_reservation, today_date),
            "gap_nights_before_next_reservation": _reservation_gap_nights(unit.current_reservation, unit.next_reservation),
            "current_channel_name": unit.current_reservation.get("_channel_name") if unit.current_reservation else None,
            "current_departure": ts_to_iso(unit.current_reservation.get("departureDate")) if unit.current_reservation else None,
            "next_channel_name": unit.next_reservation.get("_channel_name") if unit.next_reservation else None,
            "next_arrival": ts_to_iso(unit.next_reservation.get("arrivalDate")) if unit.next_reservation else None,
            "notes": _notes_to_text(unit.notes),
        }
        return _clean_attrs(attrs)


class RentlioUnitCurrentReservationStatusSensor(RentlioUnitBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        super().__init__(coordinator, entry, unit_key)
        self._attr_name = "Current Reservation Status"
        self._attr_unique_id = f"rentlio_overview_unit_{self._unit_id}_current_reservation_status"
        self._attr_icon = "mdi:bed-outline"

    @property
    def native_value(self):
        unit = self.coordinator.data["units"][self.unit_key]
        return "active" if unit.current_reservation else "no_current_reservation"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self.coordinator.data["units"][self.unit_key]
        attrs = {
            "unit_id": unit.unit_id,
            "unit_name": unit.unit_name,
            "property_id": unit.property_id,
            "property_name": unit.property_name,
        }
        attrs.update(_reservation_attrs(unit.current_reservation, "No current reservation"))
        return _clean_attrs(attrs)


class RentlioUnitNextReservationStatusSensor(RentlioUnitBase, SensorEntity):
    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        super().__init__(coordinator, entry, unit_key)
        self._attr_name = "Next Reservation Status"
        self._attr_unique_id = f"rentlio_overview_unit_{self._unit_id}_next_reservation_status"
        self._attr_icon = "mdi:calendar-arrow-right"

    @property
    def native_value(self):
        unit = self.coordinator.data["units"][self.unit_key]
        return "upcoming" if unit.next_reservation else "no_next_reservation"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self.coordinator.data["units"][self.unit_key]
        attrs = {
            "unit_id": unit.unit_id,
            "unit_name": unit.unit_name,
            "property_id": unit.property_id,
            "property_name": unit.property_name,
        }
        attrs.update(
            _reservation_attrs(
                unit.next_reservation,
                "No next reservation",
                include_days_until_arrival=True,
                today_date=_coordinator_today(self.coordinator),
            )
        )
        return _clean_attrs(attrs)


class RentlioUnitCurrentNetAveragePerNightSensor(RentlioUnitBase, SensorEntity):
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str) -> None:
        super().__init__(coordinator, entry, unit_key)
        self._attr_name = "Current Net Average Per Night"
        self._attr_unique_id = f"rentlio_overview_unit_{self._unit_id}_current_price_per_night"
        self._attr_icon = "mdi:cash"

    @property
    def native_value(self):
        unit = self.coordinator.data["units"][self.unit_key]
        current = unit.current_reservation or {}
        return _float_or_none(current.get("_net_price_per_night", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self.coordinator.data["units"][self.unit_key]
        if not unit.current_reservation:
            return {"reservation": "No current reservation"}
        return _clean_attrs(
            {
                "accommodation_average_per_night": unit.current_reservation.get("_accommodation_price_per_night"),
                "net_average_per_night": unit.current_reservation.get("_net_price_per_night"),
                "net_reservation_total": unit.current_reservation.get("_net_total_reservation_price"),
                "total_nights": unit.current_reservation.get("_nights"),
            }
        )


class RentlioAnnualGlobalRevenueSensor(RentlioPropertyAnnualBase, SensorEntity):
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, period_key: str, label: str) -> None:
        super().__init__(coordinator, entry)
        self.period_key = period_key
        self._attr_name = label
        self._attr_unique_id = f"rentlio_overview_annual_{period_key}_net_revenue"
        icon_map = {
            "elapsed_year": "mdi:calendar-start",
            "remaining_year": "mdi:calendar-end",
            "full_year": "mdi:calendar-range",
        }
        self._attr_icon = icon_map.get(period_key, "mdi:cash-clock")

    @property
    def native_value(self):
        period = self.coordinator.data.get("annual", {}).get("periods", {}).get(self.period_key, {})
        return _float_or_none(period.get("net_revenue"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        annual = self.coordinator.data.get("annual", {})
        period = annual.get("periods", {}).get(self.period_key, {})
        return _clean_attrs(
            {
                "year": annual.get("year"),
                "property_id": annual.get("property_id"),
                "property_name": annual.get("property_name"),
                **period,
            }
        )


class RentlioAnnualUnitRevenueSensor(RentlioUnitAnnualBase, SensorEntity):
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RentlioCoordinator, entry: ConfigEntry, unit_key: str, period_key: str, label: str) -> None:
        super().__init__(coordinator, entry, unit_key)
        self.period_key = period_key
        self._attr_name = label
        self._attr_unique_id = f"rentlio_overview_unit_{self._unit_id}_annual_{period_key}_net_revenue"
        icon_map = {
            "elapsed_year": "mdi:calendar-start",
            "remaining_year": "mdi:calendar-end",
            "full_year": "mdi:calendar-range",
        }
        self._attr_icon = icon_map.get(period_key, "mdi:cash-sync")

    @property
    def native_value(self):
        unit_data = self.coordinator.data.get("annual", {}).get("units", {}).get(self.unit_key, {})
        period = unit_data.get("periods", {}).get(self.period_key, {})
        return _float_or_none(period.get("net_revenue"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit_data = self.coordinator.data.get("annual", {}).get("units", {}).get(self.unit_key, {})
        period = unit_data.get("periods", {}).get(self.period_key, {})
        return _clean_attrs(
            {
                "unit_name": unit_data.get("unit_name"),
                "property_id": unit_data.get("property_id"),
                "property_name": unit_data.get("property_name"),
                **period,
            }
        )
