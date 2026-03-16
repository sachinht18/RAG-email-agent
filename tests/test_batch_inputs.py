from __future__ import annotations

import json

import pytest

from email_sdr_flow.batch import load_product_profile, load_prospects_csv_report
from email_sdr_flow.errors import InputValidationError


def test_load_product_profile_invalid_json(tmp_path):
    path = tmp_path / "product_profile.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(InputValidationError) as exc_info:
        load_product_profile(path)

    assert exc_info.value.code == "invalid_json"


def test_load_prospects_csv_report_collects_row_errors(tmp_path):
    path = tmp_path / "prospects.csv"
    path.write_text(
        "\n".join(
            [
                "account_name,target_persona_role,raw_company_notes",
                "Valid Corp,Head of Marketing,One note",
                ",Head of Marketing,Missing required account name",
                ",,",
            ]
        ),
        encoding="utf-8",
    )

    report = load_prospects_csv_report(path)

    assert len(report.prospects) == 1
    assert len(report.row_errors) == 1
    assert report.blank_row_count == 1
    assert report.row_errors[0].row_number == 3


def test_load_prospects_csv_report_rejects_unexpected_headers(tmp_path):
    path = tmp_path / "prospects.csv"
    path.write_text(
        "\n".join(
            [
                "account_name,unexpected_column",
                "Acme,foo",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as exc_info:
        load_prospects_csv_report(path)

    assert exc_info.value.code == "unexpected_csv_headers"


def test_load_prospects_csv_report_rejects_empty_csv_rows(tmp_path):
    path = tmp_path / "prospects.csv"
    path.write_text(
        "\n".join(
            [
                "account_name,target_persona_role",
                ",",
                ",",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as exc_info:
        load_prospects_csv_report(path)

    assert exc_info.value.code == "no_prospect_rows"
