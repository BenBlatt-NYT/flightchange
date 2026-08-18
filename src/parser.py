from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


PRICE_PATTERN = re.compile(r"(?P<currency>\$|USD\s*)?(?P<amount>\d[\d,]*(?:\.\d{2})?)")
TRIP_PATTERN = re.compile(r"#trip=([A-Z0-9]+)~?", re.IGNORECASE)
# Markdown table rows from the current Skiplagged MCP response.
TABLE_ROW_PATTERN = re.compile(
    r"\| \$([0-9,]+(?:\.\d{2})?) \| [^|]* \| ([^|]+) \| [^|]* \| ([^|]+) \| "
    r"Outbound:<br/>([A-Z]{3}) → ([A-Z]{3}) \(([^)]+)\) \| "
    r"\[Book\]\([^)]+#trip=([A-Z0-9]+)\)",
    re.IGNORECASE,
)
DEPART_PATTERN = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})"
)

AIRLINE_NAME_TO_CODE = {
    "delta": "DL",
    "united": "UA",
    "american": "AA",
    "jetblue": "B6",
    "jet blue": "B6",
    "alaska": "AS",
}


@dataclass
class ParsedFlightResult:
    cheapest_price: float | None
    currency: str | None
    summary: str | None


@dataclass
class ParsedFlightOffer:
    flight_number: str
    airline: str
    price: float
    stops: str
    departure_local: str
    departure_hour: int
    origin: str
    destination: str


def _normalize_flight_number(value: str) -> str:
    return re.sub(r"\s+", "", value.upper())


def _is_skiplagging_fare(line: str) -> bool:
    return "Skiplagging" in line or "Hidden city" in line


def _is_excluded_airline(line: str, exclude_airlines: list[str] | None) -> bool:
    if not exclude_airlines:
        return False
    airline_match = re.search(r"Airlines: ([^|]+)", line)
    airline = airline_match.group(1).strip() if airline_match else line
    return any(name.lower() in airline.lower() for name in exclude_airlines)


def _price_from_line(line: str) -> ParsedFlightResult | None:
    match = PRICE_PATTERN.search(line)
    if not match:
        return None
    amount = float(match.group("amount").replace(",", ""))
    label = match.group(0).strip()
    currency = "USD" if "$" in label or "USD" in label else None
    return ParsedFlightResult(amount, currency, line)


def _eligible_line(
    line: str,
    direct_only: bool,
    exclude_airlines: list[str] | None,
) -> bool:
    if not line.strip().startswith("- Price:"):
        return False
    if direct_only and _is_skiplagging_fare(line):
        return False
    if _is_excluded_airline(line, exclude_airlines):
        return False
    return True


def _airline_matches(airline: str, include_airlines: list[str] | None) -> bool:
    if not include_airlines:
        return True
    hay = airline.lower()
    return any(name.lower() in hay for name in include_airlines)


def _parse_departure(segment: str) -> tuple[str, int] | None:
    """Return (local ISO-ish stamp, local hour) from the first leg timestamp."""
    match = DEPART_PATTERN.search(segment.split("→")[0])
    if not match:
        return None
    stamp = match.group("stamp")
    # fromisoformat needs +04:00 style; stamp already has that.
    try:
        dt = datetime.fromisoformat(stamp)
    except ValueError:
        hour = int(stamp[11:13])
        return stamp, hour
    return stamp, dt.hour


def parse_flight_offers(text: str) -> list[ParsedFlightOffer]:
    """Parse all flight offers from a Skiplagged MCP search response."""
    if not text or text.startswith("Failed to fetch"):
        return []

    offers: list[ParsedFlightOffer] = []
    for match in TABLE_ROW_PATTERN.finditer(text):
        price = float(match.group(1).replace(",", ""))
        stops = match.group(2).strip()
        airline = match.group(3).strip()
        origin = match.group(4).upper()
        destination = match.group(5).upper()
        segment = match.group(6)
        flight_number = _normalize_flight_number(match.group(7))
        parsed_dep = _parse_departure(segment)
        if not parsed_dep:
            continue
        departure_local, departure_hour = parsed_dep
        offers.append(
            ParsedFlightOffer(
                flight_number=flight_number,
                airline=airline,
                price=price,
                stops=stops,
                departure_local=departure_local,
                departure_hour=departure_hour,
                origin=origin,
                destination=destination,
            )
        )
    return offers


def filter_flight_offers(
    offers: list[ParsedFlightOffer],
    *,
    direct_only: bool = True,
    include_airlines: list[str] | None = None,
    depart_before_hour: int | None = None,
) -> list[ParsedFlightOffer]:
    out: list[ParsedFlightOffer] = []
    for offer in offers:
        if direct_only and "nonstop" not in offer.stops.lower():
            continue
        if not _airline_matches(offer.airline, include_airlines):
            continue
        if depart_before_hour is not None and offer.departure_hour >= depart_before_hour:
            continue
        out.append(offer)
    # Stable: by departure then flight number
    out.sort(key=lambda o: (o.departure_local, o.flight_number))
    return out


def parse_cheapest_price(
    text: str,
    flight_number: str | None = None,
    direct_only: bool = True,
    exclude_airlines: list[str] | None = None,
) -> ParsedFlightResult:
    if not text or text.startswith("Failed to fetch"):
        return ParsedFlightResult(None, None, None)

    # Prefer structured table offers when present.
    offers = parse_flight_offers(text)
    if offers:
        if flight_number:
            target = _normalize_flight_number(flight_number)
            for offer in offers:
                if offer.flight_number != target:
                    continue
                if direct_only and "nonstop" not in offer.stops.lower():
                    continue
                if exclude_airlines and any(
                    name.lower() in offer.airline.lower() for name in exclude_airlines
                ):
                    continue
                return ParsedFlightResult(offer.price, "USD", offer.flight_number)
            return ParsedFlightResult(None, None, f"{flight_number} not found in results")

        eligible = [
            offer
            for offer in offers
            if (not direct_only or "nonstop" in offer.stops.lower())
            and not (
                exclude_airlines
                and any(name.lower() in offer.airline.lower() for name in exclude_airlines)
            )
        ]
        if not eligible:
            return ParsedFlightResult(None, None, "No direct fares found")
        best = min(eligible, key=lambda offer: offer.price)
        return ParsedFlightResult(best.price, "USD", best.flight_number)

    # Legacy bullet-list format.
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if flight_number:
        target = _normalize_flight_number(flight_number)

        for line in lines:
            if not _eligible_line(line, direct_only, exclude_airlines):
                continue
            trip_match = TRIP_PATTERN.search(line)
            if trip_match and _normalize_flight_number(trip_match.group(1)) == target:
                parsed = _price_from_line(line)
                if parsed:
                    return parsed

        for line in lines:
            if not _eligible_line(line, direct_only, exclude_airlines):
                continue
            if target not in _normalize_flight_number(line):
                continue
            parsed = _price_from_line(line)
            if parsed:
                return parsed

        return ParsedFlightResult(None, None, f"{flight_number} not found in results")

    prices: list[tuple[float, str]] = []
    for line in lines:
        if not _eligible_line(line, direct_only, exclude_airlines):
            continue
        parsed = _price_from_line(line)
        if parsed and parsed.cheapest_price is not None:
            prices.append((parsed.cheapest_price, line))

    if not prices:
        return ParsedFlightResult(None, None, "No direct fares found")

    cheapest_amount, cheapest_line = min(prices, key=lambda item: item[0])
    return ParsedFlightResult(cheapest_amount, "USD", cheapest_line)
