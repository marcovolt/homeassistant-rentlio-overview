# Rentlio Overview

Bring Rentlio into Home Assistant with a clear operational view of your property and units.

**Rentlio Overview** creates property-level and unit-level sensors for today's operations, reservation finances, annual performance, and native booking calendars. It is designed for hosts who want a practical dashboard for occupancy, arrivals, departures, revenue, and upcoming stays without leaving Home Assistant.

## What it provides

### Property overview
- Occupied units
- Vacant units
- Guests staying today
- Arrivals today
- Departures today
- Turnovers today
- Net revenue today
- Gross revenue today
- Services total today
- Channel commission amount today
- VAT amount today

### Unit overview
For each unit:
- Status
- Current reservation status
- Next reservation status
- Current net average per night

### Reservation details
For current and next reservations, the integration exposes a clean set of attributes such as:
- Arrival
- Departure
- Total nights
- Total guests
- Channel name
- OTA channel name
- Guest name
- Guest country
- Accommodation total
- Services total
- Gross reservation total
- Channel commission amount
- Channel commission rate
- Net reservation total
- Accommodation average per night
- Net average per night
- VAT rate
- VAT amount
- VAT included

### Operational planning
Per unit, the integration also exposes:
- Days until next reservation
- Gap nights before next reservation

### Annual performance
At both property and unit level:
- Elapsed year net revenue
- Remaining year net revenue
- Full year net revenue

### Native calendars
The integration creates native Home Assistant calendar entities:
- 1 property bookings calendar
- 1 bookings calendar for each unit

## Installation

### HACS (custom repository)
1. Open **HACS**.
2. Open the top-right menu.
3. Select **Custom repositories**.
4. Add your repository URL.
5. Select **Integration** as the repository type.
6. Download **Rentlio Overview**.
7. Restart Home Assistant.

### Manual
1. Copy `custom_components/rentlio_overview` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration
1. In Home Assistant, go to **Settings -> Devices & services**.
2. Select **Add integration**.
3. Search for **Rentlio Overview**.
4. Enter your Rentlio API key.
5. Select the property.
6. Optionally adjust:
   - Scan interval
   - Lookback days
   - Lookahead days

## Notes
- The integration uses the Rentlio API and depends on the fields returned by Rentlio.
- When a nominal channel commission value is provided by Rentlio, that value is used directly.
- If Rentlio does not provide a nominal channel commission, the integration falls back to calculating the commission from the percentage on the accommodation total.
- Calendar events use the booking channel as the event title.

## Disclaimer
This project is an independent Home Assistant custom integration and is not affiliated with or endorsed by Rentlio.

## ☕ Support

If this project is useful to you or improved your Home Assistant setup, you can support it here:

[Donate with Bitcoin / Crypto](./DONATE.md)

[Ko-fi / Buy me a coffee](https://ko-fi.com/marcovolt18)