from __future__ import annotations

MILES_TO_KM = 1.609344
LB_TO_KG = 0.45359237


def normalize_weight(value: float, unit: str | None) -> tuple[float, str]:
    unit_key = (unit or "kg").lower()
    if unit_key in {"lb", "lbs", "pound", "pounds"}:
        return value * LB_TO_KG, "kg"
    return value, "kg"


def normalize_energy(value: float, unit: str | None) -> tuple[float, str]:
    unit_key = (unit or "kcal").lower()
    if unit_key in {"kj", "kilojoule", "kilojoules"}:
        return value / 4.184, "kcal"
    return value, "kcal"


def normalize_grams(value: float, unit: str | None) -> tuple[float, str]:
    unit_key = (unit or "g").lower()
    if unit_key in {"mg", "milligram", "milligrams"}:
        return value / 1000.0, "g"
    return value, "g"


def normalize_distance(value: float, unit: str | None) -> tuple[float, str]:
    unit_key = (unit or "km").lower()
    if unit_key in {"mi", "mile", "miles"}:
        return value * MILES_TO_KM, "km"
    if unit_key in {"m", "meter", "meters", "metre", "metres"}:
        return value / 1000.0, "km"
    return value, "km"


def normalize_duration_hours(value: float, unit: str | None) -> tuple[float, str]:
    unit_key = (unit or "h").lower()
    if unit_key in {"s", "sec", "second", "seconds"}:
        return value / 3600.0, "h"
    if unit_key in {"m", "min", "minute", "minutes"}:
        return value / 60.0, "h"
    return value, "h"


def normalize_passthrough(value: float, unit: str | None, canonical_unit: str) -> tuple[float, str]:
    return value, canonical_unit
