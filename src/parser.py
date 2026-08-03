from __future__ import annotations

import re
from dataclasses import dataclass


PRICE_PATTERN = re.compile(r"(?P<currency>\$|USD\s*)?(?P<amount>\d[\d,]*(?:\.\d{2})?)")
TRIP_PATTERN = re.compile(r"#trip=([A-Z0-9]+)~?", re.IGNORECASE)


@dataclass
class ParsedFlightResult:
    cheapest_price: float | None
    currency: str | None
    summary: str | None


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


def parse_cheapest_price(
    text: str,
    flight_number: str | None = None,
    direct_only: bool = True,
    exclude_airlines: list[str] | None = None,
) -> ParsedFlightResult:
    if not text or text.startswith("Failed to fetch"):
        return ParsedFlightResult(None, None, None)

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
