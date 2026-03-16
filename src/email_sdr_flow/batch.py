from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from email_sdr_flow.errors import InputValidationError
from email_sdr_flow.input_validation import ensure_existing_file, load_json_file
from email_sdr_flow.runtime import log_event
from email_sdr_flow.schemas import ProductProfile, RawAccountResearch


MULTIVALUE_DELIMITER = "||"
LIST_COLUMNS = {
    "raw_company_notes",
    "raw_person_notes",
    "raw_recent_signals",
    "raw_pain_hypotheses",
    "raw_stack_signals",
    "raw_source_urls",
}
ALLOWED_PROSPECT_HEADERS = {
    "prospect_id",
    "account_name",
    "account_domain",
    "target_persona_name",
    "target_persona_role",
    "persona_name",
    "persona_role",
    "raw_company_notes",
    "raw_person_notes",
    "raw_recent_signals",
    "raw_pain_hypotheses",
    "raw_stack_signals",
    "raw_source_urls",
    "desired_cta",
}
REQUIRED_PROSPECT_HEADERS = {"account_name"}
OUTPUT_FIELD_ORDER = [
    "account_name",
    "persona",
    "account_signal_used",
    "product_proof_used",
    "chosen_angle",
    "final_subject",
    "final_draft",
    "status",
]


@dataclass(slots=True)
class ProspectRowError:
    row_number: int
    error_code: str
    error: str
    raw_row: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProspectLoadReport:
    prospects: list[tuple[int, RawAccountResearch]]
    row_errors: list[ProspectRowError] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    blank_row_count: int = 0


def load_product_profile(path: Path) -> ProductProfile:
    payload = load_json_file(path, label="product profile")
    try:
        profile = ProductProfile.model_validate(payload)
    except ValidationError as exc:
        raise InputValidationError(
            code="invalid_product_profile",
            message="Product profile does not match the expected schema.",
            context={"path": str(path), "errors": exc.errors()[:5]},
        ) from exc
    log_event("input.loaded", label="product_profile", path=str(path))
    return profile


def _split_multivalue_cell(value: str) -> list[str]:
    return [item.strip() for item in value.split(MULTIVALUE_DELIMITER) if item.strip()]


def _validate_csv_headers(fieldnames: list[str], path: Path) -> None:
    duplicates = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    if duplicates:
        raise InputValidationError(
            code="duplicate_csv_headers",
            message="Prospects CSV contains duplicate header names.",
            context={"path": str(path), "headers": duplicates},
        )
    missing = sorted(REQUIRED_PROSPECT_HEADERS - set(fieldnames))
    if missing:
        raise InputValidationError(
            code="missing_csv_headers",
            message="Prospects CSV is missing required headers.",
            context={"path": str(path), "headers": missing},
        )
    unexpected = sorted(set(fieldnames) - ALLOWED_PROSPECT_HEADERS)
    if unexpected:
        raise InputValidationError(
            code="unexpected_csv_headers",
            message="Prospects CSV contains unsupported headers.",
            context={"path": str(path), "headers": unexpected},
        )


def load_prospects_csv_report(path: Path) -> ProspectLoadReport:
    ensure_existing_file(path, label="prospects CSV", allowed_suffixes={".csv"})
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputValidationError(
                code="missing_csv_header_row",
                message="Prospects CSV is missing a header row.",
                context={"path": str(path)},
            )
        headers = [field.strip() for field in reader.fieldnames if field is not None]
        _validate_csv_headers(headers, path)

        prospects: list[tuple[int, RawAccountResearch]] = []
        row_errors: list[ProspectRowError] = []
        blank_row_count = 0

        for row_number, row in enumerate(reader, start=2):
            payload: dict[str, Any] = {}
            raw_row: dict[str, str] = {}
            for raw_key, raw_value in row.items():
                if raw_key is None:
                    continue
                key = raw_key.strip()
                value = (raw_value or "").strip()
                raw_row[key] = value
                if not key or not value:
                    continue
                if key in LIST_COLUMNS:
                    payload[key] = _split_multivalue_cell(value)
                else:
                    payload[key] = value

            if not payload:
                blank_row_count += 1
                continue
            payload.setdefault("prospect_id", f"row-{row_number - 1}")
            try:
                prospects.append((row_number, RawAccountResearch.model_validate(payload)))
            except ValidationError as exc:
                row_errors.append(
                    ProspectRowError(
                        row_number=row_number,
                        error_code="invalid_prospect_row",
                        error=str(exc),
                        raw_row=raw_row,
                    )
                )

    if not prospects and row_errors:
        log_event(
            "input.loaded_with_errors",
            label="prospects_csv",
            path=str(path),
            valid_rows=0,
            invalid_rows=len(row_errors),
            blank_rows=blank_row_count,
        )
        return ProspectLoadReport(
            prospects=[],
            row_errors=row_errors,
            headers=headers,
            blank_row_count=blank_row_count,
        )
    if not prospects:
        raise InputValidationError(
            code="no_prospect_rows",
            message="Prospects CSV did not contain any usable prospect rows.",
            context={"path": str(path), "blank_rows": blank_row_count},
        )

    log_event(
        "input.loaded",
        label="prospects_csv",
        path=str(path),
        valid_rows=len(prospects),
        invalid_rows=len(row_errors),
        blank_rows=blank_row_count,
    )
    return ProspectLoadReport(
        prospects=prospects,
        row_errors=row_errors,
        headers=headers,
        blank_row_count=blank_row_count,
    )


def load_prospects_csv(path: Path) -> list[RawAccountResearch]:
    report = load_prospects_csv_report(path)
    if report.row_errors:
        first_error = report.row_errors[0]
        raise InputValidationError(
            code="invalid_prospect_rows",
            message="Prospects CSV contains invalid rows.",
            context={
                "path": str(path),
                "invalid_row_count": len(report.row_errors),
                "first_invalid_row": first_error.to_dict(),
            },
        )
    return [prospect for _, prospect in report.prospects]


def serialize_flow_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return serialize_flow_payload(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: serialize_flow_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_flow_payload(item) for item in value]
    return value


def _format_persona(prospect: RawAccountResearch, normalized: dict[str, Any]) -> str:
    persona_name = prospect.target_persona_name or normalized.get("persona_name", "")
    persona_role = prospect.target_persona_role or normalized.get("persona_role", "")
    if persona_name and persona_role:
        return f"{persona_name} ({persona_role})"
    return persona_name or persona_role


def _pick_account_signal(
    prospect: RawAccountResearch,
    normalized: dict[str, Any],
    strategy: dict[str, Any],
) -> str:
    return (
        strategy.get("personalization_angle")
        or next(iter(normalized.get("personalization_hooks", [])), "")
        or next(iter(normalized.get("recent_signals", [])), "")
        or next(iter(prospect.raw_recent_signals), "")
        or next(iter(prospect.raw_company_notes), "")
    )


def _status_for_csv(
    serialized_result: dict[str, Any],
    *,
    error_code: str = "",
    error: str = "",
) -> str:
    if error_code or error:
        return "failed"
    if serialized_result.get("halted_for_human_review"):
        return "halted_for_review"
    return "completed"


def build_batch_output_row(
    prospect: RawAccountResearch,
    result: dict[str, Any] | None = None,
    *,
    error_code: str = "",
    error: str = "",
    blocked: bool = False,
) -> dict[str, Any]:
    serialized_result = serialize_flow_payload(result or {})
    draft = serialized_result.get("draft") or {}
    subject_lines = draft.get("subject_lines") or []
    normalized = serialized_result.get("account_research") or {}
    strategy = serialized_result.get("draft_strategy") or {}

    status = "blocked" if blocked else _status_for_csv(
        serialized_result,
        error_code=error_code,
        error=error,
    )

    return {
        "account_name": prospect.account_name,
        "persona": _format_persona(prospect, normalized),
        "account_signal_used": _pick_account_signal(prospect, normalized, strategy),
        "product_proof_used": strategy.get("proof_to_use") or draft.get("proof", ""),
        "chosen_angle": strategy.get("messaging_angle", ""),
        "final_subject": subject_lines[0] if subject_lines else "",
        "final_draft": draft.get("email_body", ""),
        "status": status,
    }


def build_batch_json_record(
    prospect: RawAccountResearch,
    result: dict[str, Any] | None = None,
    *,
    row_number: int | None = None,
    run_id: str = "",
    error_code: str = "",
    error: str = "",
) -> dict[str, Any]:
    serialized_result = serialize_flow_payload(result or {})
    status = _status_for_csv(
        serialized_result,
        error_code=error_code,
        error=error,
    )
    return {
        "run_id": run_id,
        "row_number": row_number,
        "prospect": prospect.model_dump(mode="json"),
        "status": status,
        "error_code": error_code,
        "error": error,
        "result": serialized_result,
    }


def build_batch_error_record(
    *,
    row_number: int,
    run_id: str,
    raw_row: dict[str, str],
    error_code: str,
    error: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "row_number": row_number,
        "status": "blocked",
        "error_code": error_code,
        "error": error,
        "raw_row": raw_row,
        "result": {},
    }


def build_invalid_row_output(
    *,
    row_number: int,
    raw_row: dict[str, str],
    error_code: str,
    error: str,
) -> dict[str, Any]:
    return {
        "account_name": raw_row.get("account_name", ""),
        "persona": raw_row.get("target_persona_name", "")
        or raw_row.get("persona_name", "")
        or raw_row.get("target_persona_role", "")
        or raw_row.get("persona_role", ""),
        "account_signal_used": "",
        "product_proof_used": "",
        "chosen_angle": "",
        "final_subject": "",
        "final_draft": "",
        "status": "blocked",
    }


def append_batch_csv_row(path: Path, row: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=OUTPUT_FIELD_ORDER,
            quoting=csv.QUOTE_ALL,
        )
        if should_write_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELD_ORDER})
    return path


def write_batch_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=OUTPUT_FIELD_ORDER,
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELD_ORDER})
    return path


def write_batch_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record))
            handle.write("\n")
    return path


def write_summary_json(path: Path, summary: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
