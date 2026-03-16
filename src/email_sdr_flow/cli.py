from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from email_sdr_flow.batch import (
    append_batch_csv_row,
    build_batch_error_record,
    build_batch_json_record,
    build_batch_output_row,
    build_invalid_row_output,
    load_product_profile,
    load_prospects_csv_report,
    serialize_flow_payload,
    write_batch_csv,
    write_batch_jsonl,
    write_summary_json,
)
from email_sdr_flow.errors import FrameworkError, InputValidationError
from email_sdr_flow.input_validation import (
    ensure_parent_writable,
    ensure_positive_int,
    load_json_file,
)
from email_sdr_flow.runtime import configure_logging, log_event
from email_sdr_flow.schemas import AccountResearch, RawAccountResearch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCT_PROFILE = PROJECT_ROOT / "inputs" / "product_profile.json"
DEFAULT_PROSPECTS_CSV = PROJECT_ROOT / "inputs" / "prospects.csv"
DEFAULT_COPYWRITING_DIR = PROJECT_ROOT / "knowledge" / "copywriting"
DEFAULT_PRODUCT_DOCS_DIR = PROJECT_ROOT / "knowledge" / "product_docs"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "batch_runs"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the reusable grounded outbound workflow."
    )
    parser.add_argument(
        "--product-profile",
        type=Path,
        default=DEFAULT_PRODUCT_PROFILE,
        help="Path to the reusable product profile JSON file.",
    )
    parser.add_argument(
        "--prospects-csv",
        type=Path,
        default=DEFAULT_PROSPECTS_CSV,
        help="Path to the prospects CSV used for batch generation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Batch output directory. Defaults to outputs/batch_runs/<run-id>/.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Optional explicit CSV path for flattened batch outputs.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=None,
        help="Optional explicit JSONL path for full machine-readable batch results.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional batch run id. Defaults to a UTC timestamp-based id.",
    )
    parser.add_argument(
        "--overwrite-outputs",
        action="store_true",
        help="Allow batch output files to be overwritten if they already exist.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop batch processing on the first row-level execution error.",
    )
    parser.add_argument(
        "--row-limit",
        type=int,
        default=None,
        help="Optional cap on the number of valid prospect rows to process in batch mode.",
    )
    parser.add_argument(
        "--account-research",
        type=Path,
        default=None,
        help="Path to a normalized account research JSON file for a single run.",
    )
    parser.add_argument(
        "--raw-account-research",
        type=Path,
        default=None,
        help="Path to a raw account dossier JSON file for a single run.",
    )
    parser.add_argument(
        "--copywriting-dir",
        type=Path,
        default=DEFAULT_COPYWRITING_DIR,
        help="Directory containing copywriting and positioning documents.",
    )
    parser.add_argument(
        "--product-docs-dir",
        type=Path,
        default=DEFAULT_PRODUCT_DOCS_DIR,
        help="Directory containing product documentation files.",
    )
    parser.add_argument(
        "--hitl-only",
        action="store_true",
        help="Run only the human-in-the-loop checks and stop before drafting.",
    )
    parser.add_argument(
        "--halt-on-hitl-findings",
        action="store_true",
        help="Stop before drafting when the HITL checks require human review.",
    )
    parser.add_argument(
        "--create-session",
        action="store_true",
        help="Run HITL preflight for a single prospect, persist a session, and stop.",
    )
    parser.add_argument(
        "--resume-session",
        type=str,
        default=None,
        help="Resume a previously created session after human review.",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session id to update with a review decision.",
    )
    parser.add_argument(
        "--review-scope",
        choices=["prospect_research", "product_docs", "company_understanding"],
        default=None,
        help="Which review scope to update.",
    )
    parser.add_argument(
        "--review-decision",
        choices=["approve", "reject", "clarify"],
        default=None,
        help="Human decision for a saved review scope.",
    )
    parser.add_argument(
        "--review-message",
        type=str,
        default="",
        help="Optional human note or clarification for the saved review scope.",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.account_research and args.raw_account_research:
        raise InputValidationError(
            code="conflicting_single_run_inputs",
            message="Use either --account-research or --raw-account-research, not both.",
            context={},
        )

    review_update_mode = any(
        [
            args.session_id,
            args.review_scope,
            args.review_decision,
            bool(args.review_message),
        ]
    )
    if review_update_mode and not args.review_decision:
        raise InputValidationError(
            code="missing_review_decision",
            message=(
                "Review updates require --review-decision. "
                "Provide session-id, review-scope, decision, and optional message together."
            ),
            context={},
        )
    if args.review_decision and (args.create_session or args.resume_session):
        raise InputValidationError(
            code="conflicting_session_actions",
            message="Review updates cannot be combined with create-session or resume-session.",
            context={},
        )
    if args.resume_session and (
        args.create_session or args.account_research or args.raw_account_research
    ):
        raise InputValidationError(
            code="conflicting_resume_inputs",
            message=(
                "resume-session cannot be combined with create-session, "
                "account-research, or raw-account-research."
            ),
            context={},
        )
    if args.create_session and (args.hitl_only or args.halt_on_hitl_findings):
        raise InputValidationError(
            code="conflicting_hitl_flags",
            message=(
                "create-session already stops after the human-review stage. "
                "Do not combine it with --hitl-only or --halt-on-hitl-findings."
            ),
            context={},
        )

    interactive_mode = any(
        [
            args.account_research,
            args.raw_account_research,
            args.create_session,
            args.resume_session,
            args.review_decision,
        ]
    )
    if interactive_mode and any(
        [
            args.output_dir is not None,
            args.output_csv is not None,
            args.output_jsonl is not None,
            args.run_id is not None,
            args.overwrite_outputs,
            args.fail_fast,
            args.row_limit is not None,
        ]
    ):
        raise InputValidationError(
            code="batch_only_argument",
            message=(
                "Batch-output arguments can only be used in batch mode. "
                "Remove output/run-id/row-limit/fail-fast flags for single-run or session commands."
            ),
            context={},
        )


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")


def _resolve_batch_paths(args: argparse.Namespace) -> tuple[str, Path, Path, Path]:
    run_id = args.run_id or _utc_run_id()
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)
    csv_path = args.output_csv or (output_dir / "drafts.csv")
    jsonl_path = args.output_jsonl or (output_dir / "drafts.jsonl")
    summary_path = output_dir / "summary.json"
    ensure_parent_writable(csv_path, label="batch CSV output", overwrite=args.overwrite_outputs)
    ensure_parent_writable(
        jsonl_path,
        label="batch JSONL output",
        overwrite=args.overwrite_outputs,
    )
    ensure_parent_writable(
        summary_path,
        label="batch summary output",
        overwrite=args.overwrite_outputs,
    )
    return run_id, csv_path, jsonl_path, summary_path


def load_account_research(path: Path) -> AccountResearch:
    payload = load_json_file(path, label="account research")
    try:
        return AccountResearch.model_validate(payload)
    except ValidationError as exc:
        raise InputValidationError(
            code="invalid_account_research",
            message="Account research JSON does not match the expected schema.",
            context={"path": str(path), "errors": exc.errors()[:5]},
        ) from exc


def load_raw_account_research(path: Path) -> RawAccountResearch:
    payload = load_json_file(path, label="raw account research")
    try:
        return RawAccountResearch.model_validate(payload)
    except ValidationError as exc:
        raise InputValidationError(
            code="invalid_raw_account_research",
            message="Raw account research JSON does not match the expected schema.",
            context={"path": str(path), "errors": exc.errors()[:5]},
        ) from exc


def _single_run_output(result: dict[str, object]) -> dict[str, object]:
    serialized = serialize_flow_payload(result)
    return {
        "halted_for_human_review": serialized.get("halted_for_human_review", False),
        "prospect_research_review": serialized.get("prospect_research_review"),
        "product_docs_review": serialized.get("product_docs_review"),
        "company_understanding_review": serialized.get("company_understanding_review"),
        "human_review_context": serialized.get("human_review_context"),
        "research_plan": serialized.get("research_plan"),
        "normalized_account_research": serialized.get("account_research"),
        "company_understanding": serialized.get("company_understanding"),
        "draft_strategy": serialized.get("draft_strategy"),
        "grounding_review": serialized.get("grounding_review"),
        "copy_review": serialized.get("copy_review"),
        "copywriting_kb_diagnostics": serialized.get("copywriting_kb_diagnostics"),
        "product_kb_diagnostics": serialized.get("product_kb_diagnostics"),
        "copywriting_retrieval_diagnostics": serialized.get(
            "copywriting_retrieval_diagnostics"
        ),
        "product_retrieval_diagnostics": serialized.get(
            "product_retrieval_diagnostics"
        ),
        "final_reasoning_notes": serialized.get("final_reasoning_notes"),
        "draft": serialized.get("draft"),
    }


def _should_run_batch(args: argparse.Namespace) -> bool:
    return not any(
        [
            args.account_research,
            args.raw_account_research,
            args.create_session,
            args.resume_session,
            args.review_decision,
        ]
    )


def _run_batch(args: argparse.Namespace) -> None:
    from email_sdr_flow.graph import (
        analyze_product_docs,
        build_default_dependencies,
        run_email_sdr_flow_with_dependencies,
    )

    ensure_positive_int(args.row_limit, label="row-limit")
    run_id, output_csv, output_jsonl, summary_path = _resolve_batch_paths(args)
    log_event(
        "batch.start",
        run_id=run_id,
        output_csv=str(output_csv),
        output_jsonl=str(output_jsonl),
    )
    product_profile = load_product_profile(args.product_profile)
    report = load_prospects_csv_report(args.prospects_csv)
    valid_rows = report.prospects[: args.row_limit] if args.row_limit else report.prospects

    if not valid_rows:
        csv_rows = [
            build_invalid_row_output(
                row_number=row_error.row_number,
                raw_row=row_error.raw_row,
                error_code=row_error.error_code,
                error=row_error.error,
            )
            for row_error in report.row_errors
        ]
        json_records = [
            build_batch_error_record(
                row_number=row_error.row_number,
                run_id=run_id,
                raw_row=row_error.raw_row,
                error_code=row_error.error_code,
                error=row_error.error,
            )
            for row_error in report.row_errors
        ]
        write_batch_csv(output_csv, csv_rows)
        write_batch_jsonl(output_jsonl, json_records)
        summary = {
            "mode": "batch",
            "run_id": run_id,
            "product_profile": str(args.product_profile),
            "prospects_csv": str(args.prospects_csv),
            "rows_requested": 0,
            "invalid_rows": len(report.row_errors),
            "blank_rows_skipped": report.blank_row_count,
            "completed": 0,
            "halted_for_review": 0,
            "blocked": len(report.row_errors),
            "failed": 0,
            "execution_errors": 0,
            "output_csv": str(output_csv),
            "output_jsonl": str(output_jsonl),
            "summary_json": str(summary_path),
        }
        write_summary_json(summary_path, summary)
        print(json.dumps(summary, indent=2))
        return

    dependencies = build_default_dependencies(
        copywriting_dir=args.copywriting_dir,
        product_docs_dir=args.product_docs_dir,
        required_roles={
            "HITL_REVIEWER",
            "RESEARCH_PLANNER",
            "RESEARCH_NORMALIZER",
            "QUERY_PLANNER",
            "COMPANY_UNDERSTANDING",
            "STRATEGIST",
            "DRAFTER",
            "GROUNDING_REVIEWER",
            "COPY_REVIEWER",
            "FINAL_REASONER",
        },
    )
    product_docs_review = analyze_product_docs(
        product_docs_dir=args.product_docs_dir,
        product_profile=product_profile,
        reviewer_model=dependencies["hitl_reviewer_model"],
    )

    csv_rows: list[dict[str, object]] = []
    json_records: list[dict[str, object]] = []
    execution_errors = 0

    for row_error in report.row_errors:
        csv_rows.append(
            build_invalid_row_output(
                row_number=row_error.row_number,
                raw_row=row_error.raw_row,
                error_code=row_error.error_code,
                error=row_error.error,
            )
        )
        append_batch_csv_row(output_csv, csv_rows[-1])
        json_records.append(
            build_batch_error_record(
                row_number=row_error.row_number,
                run_id=run_id,
                raw_row=row_error.raw_row,
                error_code=row_error.error_code,
                error=row_error.error,
            )
        )

    for row_number, prospect in valid_rows:
        log_event(
            "batch.row_start",
            run_id=run_id,
            row_number=row_number,
            prospect_id=prospect.prospect_id,
            account_name=prospect.account_name,
        )
        try:
            result = run_email_sdr_flow_with_dependencies(
                dependencies=dependencies,
                product_docs_dir=args.product_docs_dir,
                product_profile=product_profile,
                raw_account_research=prospect,
                product_docs_review=product_docs_review,
                hitl_only=args.hitl_only,
                halt_on_hitl_findings=args.halt_on_hitl_findings,
            )
            csv_rows.append(build_batch_output_row(prospect, result))
            append_batch_csv_row(output_csv, csv_rows[-1])
            json_records.append(
                build_batch_json_record(
                    prospect,
                    result,
                    row_number=row_number,
                    run_id=run_id,
                )
            )
        except Exception as exc:
            execution_errors += 1
            error_code = exc.code if isinstance(exc, FrameworkError) else "row_execution_failed"
            error_message = str(exc)
            csv_rows.append(
                build_batch_output_row(
                    prospect,
                    error_code=error_code,
                    error=error_message,
                )
            )
            append_batch_csv_row(output_csv, csv_rows[-1])
            json_records.append(
                build_batch_json_record(
                    prospect,
                    row_number=row_number,
                    run_id=run_id,
                    error_code=error_code,
                    error=error_message,
                )
            )
            log_event(
                "batch.row_failure",
                run_id=run_id,
                row_number=row_number,
                prospect_id=prospect.prospect_id,
                account_name=prospect.account_name,
                error_code=error_code,
            )
            if args.fail_fast:
                break

    write_batch_jsonl(output_jsonl, json_records)

    summary = {
        "mode": "batch",
        "run_id": run_id,
        "product_profile": str(args.product_profile),
        "prospects_csv": str(args.prospects_csv),
        "rows_requested": len(valid_rows),
        "invalid_rows": len(report.row_errors),
        "blank_rows_skipped": report.blank_row_count,
        "completed": sum(1 for row in csv_rows if row["status"] == "completed"),
        "halted_for_review": sum(
            1 for row in csv_rows if row["status"] == "halted_for_review"
        ),
        "blocked": sum(1 for row in csv_rows if row["status"] == "blocked"),
        "failed": sum(1 for row in csv_rows if row["status"] == "failed"),
        "execution_errors": execution_errors,
        "output_csv": str(output_csv),
        "output_jsonl": str(output_jsonl),
        "summary_json": str(summary_path),
    }
    write_summary_json(summary_path, summary)
    print(json.dumps(summary, indent=2))


def _run_single(args: argparse.Namespace) -> None:
    from email_sdr_flow.graph import create_review_session, run_email_sdr_flow

    product_profile = load_product_profile(args.product_profile)
    account_research = (
        load_account_research(args.account_research) if args.account_research else None
    )
    raw_account_research = (
        load_raw_account_research(args.raw_account_research)
        if args.raw_account_research
        else None
    )

    if args.create_session:
        log_event("single_run.create_session_start", raw_input=bool(raw_account_research))
        if account_research is None and raw_account_research is None:
            raise InputValidationError(
                code="missing_single_run_input",
                message="create-session requires account-research or raw-account-research.",
                context={},
            )
        session = create_review_session(
            product_profile=product_profile,
            account_research=account_research,
            raw_account_research=raw_account_research,
            copywriting_dir=args.copywriting_dir,
            product_docs_dir=args.product_docs_dir,
        )
        print(json.dumps(session.model_dump(mode="json"), indent=2))
        return

    if account_research is None and raw_account_research is None:
        raise InputValidationError(
            code="missing_single_run_input",
            message="Single-run mode requires account-research or raw-account-research.",
            context={},
        )

    log_event("single_run.start", raw_input=bool(raw_account_research))
    result = run_email_sdr_flow(
        product_profile=product_profile,
        account_research=account_research,
        raw_account_research=raw_account_research,
        copywriting_dir=args.copywriting_dir,
        product_docs_dir=args.product_docs_dir,
        hitl_only=args.hitl_only,
        halt_on_hitl_findings=args.halt_on_hitl_findings,
    )
    print(json.dumps(_single_run_output(result), indent=2))


def _print_error(exc: Exception) -> None:
    if isinstance(exc, FrameworkError):
        payload = {"error": exc.to_dict()}
    else:
        payload = {
            "error": {
                "code": "unexpected_error",
                "message": str(exc),
                "context": {"error_type": type(exc).__name__},
            }
        }
    print(json.dumps(payload, indent=2), file=sys.stderr)


def main() -> None:
    load_env_file(PROJECT_ROOT / ".env")
    configure_logging()
    try:
        args = parse_args()
        _validate_args(args)
        ensure_positive_int(args.row_limit, label="row-limit")

        if args.review_decision:
            from email_sdr_flow.session_store import load_session, update_review_session

            if not args.session_id or not args.review_scope:
                raise InputValidationError(
                    code="missing_review_update_args",
                    message="review-decision requires both session-id and review-scope.",
                    context={},
                )
            session = load_session(args.session_id)
            updated_session = update_review_session(
                session,
                scope=args.review_scope,
                decision=args.review_decision,
                message=args.review_message,
            )
            print(json.dumps(updated_session.model_dump(mode="json"), indent=2))
            return

        if args.resume_session:
            from email_sdr_flow.graph import resume_review_session
            from email_sdr_flow.session_store import load_session

            session = load_session(args.resume_session)
            result = resume_review_session(session)
            print(json.dumps(_single_run_output(result), indent=2))
            return

        if _should_run_batch(args):
            _run_batch(args)
            return

        _run_single(args)
    except Exception as exc:
        _print_error(exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
