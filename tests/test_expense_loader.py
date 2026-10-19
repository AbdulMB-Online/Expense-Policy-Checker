import csv
from datetime import date
from decimal import Decimal

import pytest

from loader.expense_loader import FIELDS, load_expenses


def write_rows(tmp_path, rows, headers=FIELDS, encoding="utf-8"):
    path = tmp_path / "expenses.csv"
    with path.open("w", encoding=encoding, newline="") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


@pytest.fixture
def row():
    return ["E-1", "Alice", "2024-02-29", "meals", "25.00", "Lunch", "false", "2024-03-01", ""]


def test_types_whitespace_bom_and_reordered_headers(tmp_path, row):
    row[1] = " Alice "
    row[6] = " FALSE "
    path = write_rows(tmp_path, [row[::-1]], FIELDS[::-1], "utf-8-sig")
    result = load_expenses(path)
    assert not result.errors
    expense, = result.expenses
    assert expense.employee == "Alice"
    assert expense.date == date(2024, 2, 29)
    assert expense.submission_date == date(2024, 3, 1)
    assert expense.amount == Decimal("25.00")
    assert isinstance(expense.amount, Decimal)
    assert expense.receipt_attached is False


@pytest.mark.parametrize("field", range(len(FIELDS) - 1))
def test_required_fields(tmp_path, row, field):
    row[field] = "  "
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.expenses
    assert result.errors[0].reasons == (f"{FIELDS[field]}: required field is empty",)


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "1e2", "$25", "1,000", "1.001", ".50", "1."])
def test_invalid_amounts(tmp_path, row, amount):
    row[4] = amount
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.expenses
    assert result.errors[0].reasons[0].startswith("amount:")


@pytest.mark.parametrize("amount", ["0", "0.00", "0.01", "50.00", "50.01", "999999999999999999999999999999.99"])
def test_valid_amounts_include_policy_violations(tmp_path, row, amount):
    row[4] = amount
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.errors
    assert result.expenses[0].amount == Decimal(amount)


@pytest.mark.parametrize("value", ["2026-02-29", "2026-02-30", "2026-1-01", "20260101", "0000-01-01", "10/05/2026"])
def test_invalid_dates(tmp_path, row, value):
    row[2] = value
    result = load_expenses(write_rows(tmp_path, [row]))
    assert result.errors[0].reasons[0].startswith("date:")


@pytest.mark.parametrize("value", ["bad", "2026-02-30", "2024-2-29"])
def test_invalid_submission_dates(tmp_path, row, value):
    row[7] = value
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.expenses
    assert result.errors[0].reasons[0].startswith("submission_date:")


def test_late_and_restricted_expenses_are_valid_input(tmp_path, row):
    row[3] = "alcohol"
    row[7] = "2024-04-01"
    assert not load_expenses(write_rows(tmp_path, [row])).errors


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "two"])
def test_supplied_nights_must_be_positive_integer(tmp_path, row, value):
    row[3], row[8] = "hotel", value
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.expenses
    assert result.errors[0].reasons[0].startswith("nights:")


def test_loader_does_not_apply_category_or_submission_policy(tmp_path, row):
    row[3], row[7], row[8] = "hotel", "2024-02-28", ""
    result = load_expenses(write_rows(tmp_path, [row]))
    assert not result.errors
    expense, = result.expenses
    assert expense.nights is None
    assert expense.submission_date < expense.date


def test_hotel_total_and_nights_are_preserved(tmp_path, row):
    row[3], row[4], row[8] = "hotel", "400.00", "2"
    expense, = load_expenses(write_rows(tmp_path, [row])).expenses
    assert expense.nights == 2
    assert expense.amount == Decimal("400.00")


@pytest.mark.parametrize("value, expected", [("true", True), ("TRUE", True), ("False", False)])
def test_receipt_values(tmp_path, row, value, expected):
    row[6] = value
    assert load_expenses(write_rows(tmp_path, [row])).expenses[0].receipt_attached is expected


@pytest.mark.parametrize("value", ["yes", "no", "1", "0", "maybe"])
def test_invalid_receipt_values(tmp_path, row, value):
    row[6] = value
    assert load_expenses(write_rows(tmp_path, [row])).errors[0].reasons[0].startswith("receipt_attached:")


def test_collects_reasons_and_continues_without_reserving_invalid_id(tmp_path, row):
    invalid = row.copy()
    invalid[1], invalid[2], invalid[4] = "", "bad", "-1"
    result = load_expenses(write_rows(tmp_path, [invalid, row, row]))
    assert len(result.expenses) == 1
    assert len(result.errors) == 2
    assert len(result.errors[0].reasons) == 3
    assert result.errors[0].line_number == 2
    assert result.errors[1].expense_id == "E-1"
    assert "duplicates" in result.errors[1].reasons[0]


def test_business_duplicates_are_valid(tmp_path, row):
    second = row.copy()
    second[0] = "E-2"
    result = load_expenses(write_rows(tmp_path, [row, second]))
    assert len(result.expenses) == 2
    assert not result.errors


def test_field_counts_blank_lines_and_multiline_descriptions(tmp_path, row):
    row[5] = "Lunch, with client\nSecond line"
    path = write_rows(tmp_path, [[], row, row[:-1], row + ["extra"], ["E-2"] + row[1:]])
    result = load_expenses(path)
    assert len(result.expenses) == 2
    assert result.expenses[0].description == row[5]
    assert [error.line_number for error in result.errors] == [5, 7]
    assert [error.expense_id for error in result.errors] == ["E-1", "E-1"]


@pytest.mark.parametrize("headers", [FIELDS, ("employee", "id", *FIELDS[2:])])
@pytest.mark.parametrize("extra_fields", [False, True])
@pytest.mark.parametrize("expense_id, expected_id", [(" EXP-123 ", "EXP-123"), ("  ", None)])
def test_field_count_errors_preserve_available_id(tmp_path, row, headers, extra_fields, expense_id, expected_id):
    row[0] = expense_id
    record = dict(zip(FIELDS, row))
    values = [record[field] for field in headers]
    values = values + ["extra"] if extra_fields else values[:-1]
    result = load_expenses(write_rows(tmp_path, [values], headers))
    assert not result.expenses
    error, = result.errors
    assert error.line_number == 2
    assert error.expense_id == expected_id
    assert error.reasons == (f"Expected {len(headers)} fields, got {len(values)}",)


def test_field_count_error_without_id_column_value(tmp_path, row):
    headers = (*FIELDS[1:], "id")
    result = load_expenses(write_rows(tmp_path, [row[1:]], headers))
    assert not result.expenses
    error, = result.errors
    assert error.expense_id is None
    assert error.reasons == ("Expected 9 fields, got 8",)


@pytest.mark.parametrize("headers", [[], FIELDS[:-1], (*FIELDS, "currency"), (*FIELDS[:-1], "id")])
def test_bad_headers(tmp_path, headers):
    with pytest.raises(ValueError, match="headers"):
        load_expenses(write_rows(tmp_path, [], headers))


def test_empty_and_header_only_files(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(ValueError):
        load_expenses(path)
    result = load_expenses(write_rows(tmp_path, []))
    assert not result.expenses and not result.errors


def test_file_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_expenses(tmp_path / "absent.csv")
    path = tmp_path / "bad.csv"
    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        load_expenses(path)
    path.write_text(",".join(FIELDS) + '\n"unterminated')
    with pytest.raises(csv.Error):
        load_expenses(path)
