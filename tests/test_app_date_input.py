from datetime import date

from app import coerce_date_input_value


def test_coerce_date_input_value_keeps_in_range_date() -> None:
    value = date(2024, 6, 15)
    min_value = date(2023, 1, 1)
    max_value = date(2025, 12, 31)

    assert coerce_date_input_value(value, min_value, max_value) == value


def test_coerce_date_input_value_falls_back_when_out_of_range() -> None:
    value = date(2030, 1, 1)
    min_value = date(2020, 1, 1)
    max_value = date(2024, 12, 31)

    assert coerce_date_input_value(value, min_value, max_value) == date(2000, 1, 1)
