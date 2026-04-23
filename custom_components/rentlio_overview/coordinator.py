from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, date
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RentlioApiClient, RentlioApiError
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_TIMEZONE, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnitState:
    unit_id: int | None
    unit_name: str
    property_id: int | None
    property_name: str
    occupied: bool
    status: str
    has_check_in_today: bool
    has_check_out_today: bool
    has_turnover_today: bool
    current_reservation: dict[str, Any] | None
    next_reservation: dict[str, Any] | None
    reservations: list[dict[str, Any]]
    notes: list[str]


class RentlioCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: RentlioApiClient,
        property_id: int,
        scan_interval_seconds: int | None,
        lookback_days: int,
        lookahead_days: int,
    ) -> None:
        self.api = api
        self.property_id = int(property_id)
        self.lookback_days = int(lookback_days)
        self.lookahead_days = int(lookahead_days)
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=scan_interval_seconds or DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            now = datetime.now(self.tz)
            today = now.date()
            now_ts = int(now.timestamp())
            realtime_date_from = (now - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
            realtime_date_to = (now + timedelta(days=self.lookahead_days)).strftime("%Y-%m-%d")
            year_start = date(today.year, 1, 1)
            year_end = date(today.year, 12, 31)
            annual_date_from = year_start.strftime("%Y-%m-%d")
            annual_date_to = year_end.strftime("%Y-%m-%d")

            properties = await self.api.get_properties(self.hass)
            property_map = {int(p["id"]): p for p in properties if "id" in p}
            sales_channel_map: dict[str, str] = {}
            units: list[dict[str, Any]] = []

            try:
                units.extend(await self.api.get_units(self.hass, self.property_id))
            except RentlioApiError as err:
                _LOGGER.warning("Failed loading units for property %s: %s", self.property_id, err)

            try:
                channels = await self.api.get_sales_channels(self.hass, self.property_id)
                for channel in channels:
                    cid = channel.get("id")
                    if cid is not None:
                        sales_channel_map[str(cid)] = str(channel.get("name") or cid)
            except RentlioApiError as err:
                _LOGGER.warning("Failed loading sales channels for property %s: %s", self.property_id, err)

            unit_states: dict[str, UnitState] = {}
            annual_unit_data: dict[str, Any] = {}
            total_reservations = 0
            total_people_present = 0
            daily_revenue_today = 0.0
            daily_vat_today = 0.0
            daily_services_today = 0.0
            daily_channel_commission_today = 0.0
            daily_gross_revenue_today = 0.0
            paid_present_count = 0
            unpaid_present_count = 0
            check_ins_today = 0
            check_outs_today = 0
            turnovers_today = 0
            overview_vat_rates: list[float] = []

            for unit in units:
                unit_id = unit.get("id")
                property_id = unit.get("propertiesId")
                unit_name = str(unit.get("name") or f"Unit {unit_id}")
                property_name = str(property_map.get(int(property_id), {}).get("name") or f"Property {property_id}")
                notes: list[str] = []
                reservations: list[dict[str, Any]] = []
                annual_reservations: list[dict[str, Any]] = []
                if unit_id is None:
                    notes.append("Missing unit id from units API")
                else:
                    try:
                        reservations = await self.api.get_reservations_for_unit(self.hass, unit_id, realtime_date_from, realtime_date_to)
                    except RentlioApiError as err:
                        notes.append(f"Reservations API error: {err}")
                    try:
                        annual_reservations = await self.api.get_reservations_for_unit(self.hass, unit_id, annual_date_from, annual_date_to)
                    except RentlioApiError as err:
                        notes.append(f"Annual reservations API error: {err}")
                total_reservations += len(reservations)

                normalized = sorted(
                    [r for r in reservations if int(r.get("status", 0) or 0) == 1],
                    key=lambda r: int(r.get("arrivalDate", 0) or 0),
                )
                annual_normalized = sorted(
                    [r for r in annual_reservations if int(r.get("status", 0) or 0) == 1],
                    key=lambda r: int(r.get("arrivalDate", 0) or 0),
                )
                for res in normalized:
                    enrich_reservation(res, sales_channel_map, today)
                for res in annual_normalized:
                    enrich_reservation(res, sales_channel_map, today)

                current_res = None
                for res in normalized:
                    arrival = int(res.get("arrivalDate", 0) or 0)
                    departure = int(res.get("departureDate", 0) or 0)
                    if arrival <= now_ts < departure:
                        current_res = res
                        break

                next_res = None
                for res in normalized:
                    if current_res and res.get("id") == current_res.get("id"):
                        continue
                    arrival_ts = int(res.get("arrivalDate", 0) or 0)
                    if arrival_ts >= now_ts:
                        next_res = res
                        break

                arrivals_today = [r for r in normalized if ts_to_date(r.get("arrivalDate")) == today]
                departures_today = [r for r in normalized if ts_to_date(r.get("departureDate")) == today]
                has_check_in_today = len(arrivals_today) > 0
                has_check_out_today = len(departures_today) > 0
                has_turnover_today = has_check_in_today and has_check_out_today

                occupied = current_res is not None
                if has_turnover_today:
                    status = "turnover_today"
                elif has_check_in_today:
                    status = "arrival_today"
                elif has_check_out_today:
                    status = "departure_today"
                elif occupied:
                    status = "occupied"
                else:
                    status = "vacant"

                if occupied and current_res:
                    total_people_present += reservation_guest_total(current_res)
                    daily_revenue_today += float(current_res.get("_net_price_per_night", 0) or 0)
                    daily_gross_revenue_today += float(current_res.get("_gross_price_per_night", 0) or 0)
                    daily_services_today += float(current_res.get("_services_price_per_night", 0) or 0)
                    daily_channel_commission_today += float(current_res.get("_channel_commission_per_night", 0) or 0)
                    daily_vat_today += float(current_res.get("_vat_per_night", 0) or 0)
                    if current_res.get("vatRate") not in (None, ""):
                        try:
                            overview_vat_rates.append(float(current_res.get("vatRate")))
                        except (TypeError, ValueError):
                            pass
                    if bool(current_res.get("isPaid")):
                        paid_present_count += 1
                    else:
                        unpaid_present_count += 1
                if has_check_in_today:
                    check_ins_today += 1
                if has_check_out_today:
                    check_outs_today += 1
                if has_turnover_today:
                    turnovers_today += 1

                key = str(unit_id if unit_id is not None else unit_name)
                unit_states[key] = UnitState(
                    unit_id=int(unit_id) if unit_id is not None else None,
                    unit_name=unit_name,
                    property_id=int(property_id) if property_id is not None else None,
                    property_name=property_name,
                    occupied=occupied,
                    status=status,
                    has_check_in_today=has_check_in_today,
                    has_check_out_today=has_check_out_today,
                    has_turnover_today=has_turnover_today,
                    current_reservation=current_res,
                    next_reservation=next_res,
                    reservations=normalized,
                    notes=notes,
                )
                annual_unit_data[key] = compute_unit_annual_metrics(
                    unit_name=unit_name,
                    property_id=int(property_id) if property_id is not None else None,
                    property_name=property_name,
                    reservations=annual_normalized,
                    year_start=year_start,
                    today=today,
                    year_end=year_end,
                )

            occupied_count = sum(1 for u in unit_states.values() if u.occupied)
            annual = build_annual_data(annual_unit_data, year_start, today, year_end)
            avg_vat_rate_today = round(sum(overview_vat_rates) / len(overview_vat_rates), 2) if overview_vat_rates else None
            return {
                "property_count": 1,
                "property_ids": [self.property_id],
                "properties": property_map,
                "unit_count": len(unit_states),
                "units": unit_states,
                "reservation_count": total_reservations,
                "occupied_count": occupied_count,
                "date_from": realtime_date_from,
                "date_to": realtime_date_to,
                "now": now.isoformat(),
                "timezone": DEFAULT_TIMEZONE,
                "lookback_days": self.lookback_days,
                "lookahead_days": self.lookahead_days,
                "sales_channels": sales_channel_map,
                "check_ins_today": check_ins_today,
                "check_outs_today": check_outs_today,
                "turnovers_today": turnovers_today,
                "current_people_total": total_people_present,
                "daily_revenue_today": round(daily_revenue_today, 2),
                "daily_gross_revenue_today": round(daily_gross_revenue_today, 2),
                "daily_services_today": round(daily_services_today, 2),
                "daily_channel_commission_today": round(daily_channel_commission_today, 2),
                "daily_vat_today": round(daily_vat_today, 2),
                "avg_vat_rate_today": avg_vat_rate_today,
                "paid_present_count": paid_present_count,
                "unpaid_present_count": unpaid_present_count,
                "annual": annual,
            }
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err


def ts_to_iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), ZoneInfo(DEFAULT_TIMEZONE)).isoformat()


def ts_to_date(ts: int | None) -> date | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), ZoneInfo(DEFAULT_TIMEZONE)).date()


def reservation_guest_total(reservation: dict[str, Any]) -> int:
    return int(reservation.get("adults", 0) or 0) + int(reservation.get("childrenAbove12", 0) or 0) + int(reservation.get("childrenUnder12", 0) or 0)


def reservation_nights(reservation: dict[str, Any]) -> int | None:
    total_nights = reservation.get("totalNights")
    if total_nights not in (None, ""):
        return int(total_nights)
    arr = reservation.get("arrivalDate")
    dep = reservation.get("departureDate")
    if not arr or not dep:
        return None
    delta = datetime.fromtimestamp(int(dep), ZoneInfo(DEFAULT_TIMEZONE)).date() - datetime.fromtimestamp(int(arr), ZoneInfo(DEFAULT_TIMEZONE)).date()
    return delta.days


def _float_or_zero(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def reservation_accommodation_total(reservation: dict[str, Any]) -> float:
    return round(_float_or_zero(reservation.get("totalPrice")), 2)


def reservation_gross_total(reservation: dict[str, Any]) -> float:
    return round(_float_or_zero(reservation.get("totalReservationPrice")), 2)


def reservation_channel_commission_total(reservation: dict[str, Any]) -> float:
    commission_nominal = reservation.get("channelCommissionNominal")
    if commission_nominal not in (None, ""):
        return round(_float_or_zero(commission_nominal), 2)
    commission_pct = _float_or_zero(reservation.get("channelCommissionPercentage"))
    if not commission_pct:
        return 0.0
    accommodation_total = reservation_accommodation_total(reservation)
    return round(accommodation_total * commission_pct / 100, 2)


def reservation_net_total(reservation: dict[str, Any]) -> float:
    gross_total = reservation_gross_total(reservation)
    commission = reservation_channel_commission_total(reservation)
    return round(gross_total - commission, 2)


def reservation_accommodation_price_per_night(reservation: dict[str, Any]) -> float | None:
    nights = reservation_nights(reservation)
    if not nights:
        return None
    return round(reservation_accommodation_total(reservation) / nights, 2)


def reservation_net_price_per_night(reservation: dict[str, Any]) -> float | None:
    nights = reservation_nights(reservation)
    if not nights:
        return None
    return round(reservation_net_total(reservation) / nights, 2)


def reservation_days_since_booking(reservation: dict[str, Any], today_date: date) -> int | None:
    booked_at = reservation.get("bookedAt")
    booked_date = ts_to_date(booked_at)
    if booked_date is None:
        return None
    return (today_date - booked_date).days


def reservation_lead_days(reservation: dict[str, Any]) -> int | None:
    booked_date = ts_to_date(reservation.get("bookedAt"))
    arrival_date = ts_to_date(reservation.get("arrivalDate"))
    if booked_date is None or arrival_date is None:
        return None
    return (arrival_date - booked_date).days


def _reservation_channel_id(reservation: dict[str, Any]) -> str | None:
    for key in ("salesChannelsId", "channelId", "channelID"):
        value = reservation.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def enrich_reservation(reservation: dict[str, Any], sales_channels: dict[str, str], today_date: date) -> None:
    cid_str = _reservation_channel_id(reservation)
    reservation["_channel_name"] = reservation.get("salesChannelName") or reservation.get("otaChannelName") or (sales_channels.get(cid_str) if cid_str else None) or cid_str
    reservation["_guest_total"] = reservation_guest_total(reservation)
    reservation["_nights"] = reservation_nights(reservation)
    reservation["_accommodation_total_price"] = reservation_accommodation_total(reservation)
    reservation["_gross_total_reservation_price"] = reservation_gross_total(reservation)
    reservation["_channel_commission_total"] = reservation_channel_commission_total(reservation)
    reservation["_net_total_reservation_price"] = reservation_net_total(reservation)
    reservation["_accommodation_price_per_night"] = reservation_accommodation_price_per_night(reservation)
    reservation["_net_price_per_night"] = reservation_net_price_per_night(reservation)
    reservation["_gross_price_per_night"] = round(reservation_gross_total(reservation) / reservation["_nights"], 2) if reservation.get("_nights") else None
    reservation["_services_price_per_night"] = round(_float_or_zero(reservation.get("totalServicesPrice")) / reservation["_nights"], 2) if reservation.get("_nights") else None
    reservation["_channel_commission_per_night"] = round(reservation_channel_commission_total(reservation) / reservation["_nights"], 2) if reservation.get("_nights") else None
    reservation["_vat_per_night"] = round(_float_or_zero(reservation.get("vatAmount")) / reservation["_nights"], 2) if reservation.get("_nights") else None
    reservation["_days_since_booking"] = reservation_days_since_booking(reservation, today_date)
    reservation["_lead_days"] = reservation_lead_days(reservation)


def daterange_days(start: date, end: date) -> int:
    if end < start:
        return 0
    return (end - start).days + 1


def period_overlap_nights(arrival: date | None, departure: date | None, period_start: date, period_end: date) -> int:
    if arrival is None or departure is None:
        return 0
    last_night = departure - timedelta(days=1)
    overlap_start = max(arrival, period_start)
    overlap_end = min(last_night, period_end)
    if overlap_end < overlap_start:
        return 0
    return daterange_days(overlap_start, overlap_end)


def compute_period_metrics(reservations: list[dict[str, Any]], period_start: date, period_end: date, unit_count: int = 1) -> dict[str, Any]:
    days_in_period = daterange_days(period_start, period_end)
    available_unit_nights = days_in_period * unit_count
    sold_nights = 0
    guest_nights = 0
    net_revenue = 0.0
    gross_revenue = 0.0
    total_services = 0.0
    total_channel_commission = 0.0
    total_vat_amount = 0.0
    checkins = 0
    total_guests = 0
    reservation_count = 0
    lead_days_values: list[int] = []
    los_values: list[int] = []
    guest_values: list[int] = []
    vat_rates: list[float] = []

    for res in reservations:
        arrival = ts_to_date(res.get("arrivalDate"))
        departure = ts_to_date(res.get("departureDate"))
        nights = int(res.get("_nights") or 0)
        overlap_nights = period_overlap_nights(arrival, departure, period_start, period_end)
        if overlap_nights <= 0 or nights <= 0:
            # still count check-in related metrics if arrival within period even if no nights? usually impossible
            if arrival and period_start <= arrival <= period_end:
                reservation_count += 1
                checkins += 1
                total_guests += int(res.get("_guest_total") or 0)
                lead = res.get("_lead_days")
                if lead is not None:
                    lead_days_values.append(int(lead))
                if nights > 0:
                    los_values.append(nights)
                guest_values.append(int(res.get("_guest_total") or 0))
            continue
        sold_nights += overlap_nights
        guest_total = int(res.get("_guest_total") or 0)
        guest_nights += overlap_nights * guest_total
        net_revenue += overlap_nights * _float_or_zero(res.get("_net_price_per_night"))
        gross_revenue += overlap_nights * _float_or_zero(res.get("_gross_price_per_night"))
        total_services += overlap_nights * _float_or_zero(res.get("_services_price_per_night"))
        total_channel_commission += overlap_nights * _float_or_zero(res.get("_channel_commission_per_night"))
        total_vat_amount += overlap_nights * _float_or_zero(res.get("_vat_per_night"))
        if arrival and period_start <= arrival <= period_end:
            reservation_count += 1
            checkins += 1
            total_guests += guest_total
            lead = res.get("_lead_days")
            if lead is not None:
                lead_days_values.append(int(lead))
            if nights > 0:
                los_values.append(nights)
            guest_values.append(guest_total)
            if res.get("vatRate") not in (None, ""):
                try:
                    vat_rates.append(float(res.get("vatRate")))
                except (TypeError, ValueError):
                    pass

    free_nights = max(available_unit_nights - sold_nights, 0)
    occupancy_rate = round((sold_nights / available_unit_nights) * 100, 2) if available_unit_nights else 0.0
    avg_booking_lead_days = round(sum(lead_days_values) / len(lead_days_values), 2) if lead_days_values else None
    avg_length_of_stay = round(sum(los_values) / len(los_values), 2) if los_values else None
    avg_daily_net_revenue = round(net_revenue / days_in_period, 2) if days_in_period else 0.0
    avg_net_per_sold_night = round(net_revenue / sold_nights, 2) if sold_nights else 0.0
    avg_guests_per_checkin = round(total_guests / checkins, 2) if checkins else None
    avg_vat_rate = round(sum(vat_rates) / len(vat_rates), 2) if vat_rates else None
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days_in_period": days_in_period,
        "available_unit_nights": available_unit_nights,
        "sold_nights": sold_nights,
        "free_nights": free_nights,
        "occupancy_rate": occupancy_rate,
        "guest_nights": guest_nights,
        "arrivals": checkins,
        "total_guests": total_guests,
        "reservation_count": reservation_count,
        "net_revenue": round(net_revenue, 2),
        "gross_revenue": round(gross_revenue, 2),
        "services_total": round(total_services, 2),
        "channel_commission_amount": round(total_channel_commission, 2),
        "vat_amount": round(total_vat_amount, 2),
        "avg_vat_rate": avg_vat_rate,
        "avg_booking_lead_days": avg_booking_lead_days,
        "avg_length_of_stay": avg_length_of_stay,
        "avg_daily_net_revenue": avg_daily_net_revenue,
        "avg_net_per_sold_night": avg_net_per_sold_night,
        "avg_guests_per_arrival": avg_guests_per_checkin,
    }


def compute_unit_annual_metrics(unit_name: str, property_id: int | None, property_name: str, reservations: list[dict[str, Any]], year_start: date, today: date, year_end: date) -> dict[str, Any]:
    remaining_start = min(today + timedelta(days=1), year_end)
    if remaining_start > year_end:
        remaining_start = year_end
    periods = {
        "elapsed_year": compute_period_metrics(reservations, year_start, today, unit_count=1),
        "remaining_year": compute_period_metrics(reservations, remaining_start, year_end, unit_count=1) if today < year_end else compute_period_metrics([], year_end, year_end, unit_count=1),
        "full_year": compute_period_metrics(reservations, year_start, year_end, unit_count=1),
    }
    return {
        "unit_name": unit_name,
        "property_id": property_id,
        "property_name": property_name,
        "periods": periods,
    }


def build_annual_data(unit_data: dict[str, Any], year_start: date, today: date, year_end: date) -> dict[str, Any]:
    unit_count = len(unit_data)
    remaining_start = min(today + timedelta(days=1), year_end)
    if remaining_start > year_end:
        remaining_start = year_end
    periods = {
        "elapsed_year": {"start": year_start, "end": today},
        "remaining_year": {"start": remaining_start, "end": year_end},
        "full_year": {"start": year_start, "end": year_end},
    }
    structure_periods: dict[str, Any] = {}
    for key, meta in periods.items():
        start = meta["start"]
        end = meta["end"]
        days_in_period = daterange_days(start, end)
        metrics = {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "days_in_period": days_in_period,
            "available_unit_nights": days_in_period * unit_count,
            "sold_nights": 0,
            "free_nights": days_in_period * unit_count,
            "occupancy_rate": 0.0,
            "guest_nights": 0,
            "arrivals": 0,
            "total_guests": 0,
            "reservation_count": 0,
            "net_revenue": 0.0,
            "gross_revenue": 0.0,
            "services_total": 0.0,
            "channel_commission_amount": 0.0,
            "vat_amount": 0.0,
            "avg_vat_rate": None,
            "avg_booking_lead_days": None,
            "avg_length_of_stay": None,
            "avg_daily_net_revenue": 0.0,
            "avg_net_per_sold_night": 0.0,
            "avg_guests_per_arrival": None,
        }
        lead_vals=[]; los_vals=[]; guest_vals=[]; vat_vals=[]
        for unit_key, unit in unit_data.items():
            period = unit["periods"][key]
            for fld in ("sold_nights","guest_nights","arrivals","total_guests","reservation_count"):
                metrics[fld] += period[fld]
            for fld in ("net_revenue","gross_revenue","services_total","channel_commission_amount","vat_amount"):
                metrics[fld] += period[fld]
            lead = period.get("avg_booking_lead_days")
            if lead is not None:
                lead_vals.append(float(lead))
            los = period.get("avg_length_of_stay")
            if los is not None:
                los_vals.append(float(los))
            guest = period.get("avg_guests_per_arrival")
            if guest is not None:
                guest_vals.append(float(guest))
            vr = period.get("avg_vat_rate")
            if vr is not None:
                vat_vals.append(float(vr))
        metrics["free_nights"] = max(metrics["available_unit_nights"] - metrics["sold_nights"], 0)
        metrics["occupancy_rate"] = round((metrics["sold_nights"] / metrics["available_unit_nights"]) * 100, 2) if metrics["available_unit_nights"] else 0.0
        metrics["net_revenue"] = round(metrics["net_revenue"], 2)
        metrics["gross_revenue"] = round(metrics["gross_revenue"], 2)
        metrics["services_total"] = round(metrics["services_total"], 2)
        metrics["channel_commission_amount"] = round(metrics["channel_commission_amount"], 2)
        metrics["vat_amount"] = round(metrics["vat_amount"], 2)
        metrics["avg_daily_net_revenue"] = round(metrics["net_revenue"] / days_in_period, 2) if days_in_period else 0.0
        metrics["avg_net_per_sold_night"] = round(metrics["net_revenue"] / metrics["sold_nights"], 2) if metrics["sold_nights"] else 0.0
        metrics["avg_booking_lead_days"] = round(sum(lead_vals) / len(lead_vals), 2) if lead_vals else None
        metrics["avg_length_of_stay"] = round(sum(los_vals) / len(los_vals), 2) if los_vals else None
        metrics["avg_guests_per_arrival"] = round(sum(guest_vals) / len(guest_vals), 2) if guest_vals else None
        metrics["avg_vat_rate"] = round(sum(vat_vals) / len(vat_vals), 2) if vat_vals else None
        structure_periods[key] = metrics
    return {
        "year": year_start.year,
        "property_id": next((u.get("property_id") for u in unit_data.values() if u.get("property_id") is not None), None),
        "property_name": next((u.get("property_name") for u in unit_data.values() if u.get("property_name")), None),
        "unit_count": unit_count,
        "periods": structure_periods,
        "units": unit_data,
    }
