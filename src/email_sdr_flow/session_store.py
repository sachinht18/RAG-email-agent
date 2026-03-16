from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from email_sdr_flow.errors import SessionStateError
from email_sdr_flow.input_validation import load_json_file, validate_session_id
from email_sdr_flow.runtime import log_event
from email_sdr_flow.schemas import (
    HumanReviewAction,
    HumanReviewReport,
    ReviewCheckpoint,
    WorkflowSession,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = PROJECT_ROOT / ".sessions"
EDITABLE_SESSION_STATUSES = {"pending_review", "ready_to_resume", "rejected"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_session_id() -> str:
    return uuid4().hex[:12]


def ensure_sessions_dir() -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR


def session_path(session_id: str) -> Path:
    validated_id = validate_session_id(session_id)
    return ensure_sessions_dir() / f"{validated_id}.json"


def save_session(session: WorkflowSession) -> Path:
    path = session_path(session.session_id)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(session.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    log_event("session.saved", session_id=session.session_id, status=session.status)
    return path


def load_session(session_id: str) -> WorkflowSession:
    path = session_path(session_id)
    if not path.exists():
        raise SessionStateError(
            code="session_not_found",
            message="Session file was not found.",
            context={"session_id": session_id, "path": str(path)},
        )
    payload = load_json_file(path, label="session")
    try:
        return WorkflowSession.model_validate(payload)
    except ValidationError as exc:
        raise SessionStateError(
            code="invalid_session_payload",
            message="Session file is malformed or incompatible with the current schema.",
            context={"session_id": session_id, "path": str(path), "errors": exc.errors()[:5]},
        ) from exc


def default_checkpoint(report: HumanReviewReport) -> ReviewCheckpoint:
    if report.requires_human_review:
        return ReviewCheckpoint(report=report)
    return ReviewCheckpoint(
        report=report,
        action={
            "decision": "approve",
            "message": "Auto-approved because no human review was required.",
            "decided_at": utc_now_iso(),
        },
    )


def session_status(
    prospect_research_review: ReviewCheckpoint,
    product_docs_review: ReviewCheckpoint,
    company_understanding_review: ReviewCheckpoint | None = None,
) -> str:
    decisions = [
        prospect_research_review.action.decision,
        product_docs_review.action.decision,
    ]
    if company_understanding_review is not None:
        decisions.append(company_understanding_review.action.decision)
    if any(decision == "reject" for decision in decisions):
        return "rejected"
    if all(decision in {"approve", "clarify"} for decision in decisions):
        return "ready_to_resume"
    return "pending_review"


def assert_resume_ready(session: WorkflowSession) -> None:
    if session.status == "completed":
        raise SessionStateError(
            code="session_already_completed",
            message="Completed sessions cannot be resumed again.",
            context={"session_id": session.session_id},
        )
    if session.status != "ready_to_resume":
        raise SessionStateError(
            code="session_not_ready",
            message="Session is not ready to resume. Resolve all pending reviews first.",
            context={"session_id": session.session_id, "status": session.status},
        )
    if session.product_profile is None:
        raise SessionStateError(
            code="session_missing_product_profile",
            message="Session is missing the product profile required to resume.",
            context={"session_id": session.session_id},
        )
    if session.account_research is None and session.raw_account_research is None:
        raise SessionStateError(
            code="session_missing_research",
            message="Session is missing both raw and normalized account research.",
            context={"session_id": session.session_id},
        )
    if session.company_understanding is None or session.company_understanding_review is None:
        raise SessionStateError(
            code="session_missing_company_understanding",
            message="Session is missing the company-understanding artifact required to resume.",
            context={"session_id": session.session_id},
        )
    if not session.copywriting_snippets:
        raise SessionStateError(
            code="session_missing_copywriting_snippets",
            message="Session is missing saved copywriting grounding snippets required to resume.",
            context={"session_id": session.session_id},
        )
    if not session.product_snippets:
        raise SessionStateError(
            code="session_missing_product_snippets",
            message="Session is missing saved product grounding snippets required to resume.",
            context={"session_id": session.session_id},
        )


def update_review_session(
    session: WorkflowSession,
    *,
    scope: str,
    decision: str,
    message: str = "",
) -> WorkflowSession:
    if session.status not in EDITABLE_SESSION_STATUSES:
        raise SessionStateError(
            code="session_not_editable",
            message="Only pending, ready-to-resume, or rejected sessions can be updated.",
            context={"session_id": session.session_id, "status": session.status},
        )
    if scope not in {"prospect_research", "product_docs", "company_understanding"}:
        raise SessionStateError(
            code="invalid_review_scope",
            message="Review scope is not recognized.",
            context={"scope": scope},
        )
    if decision not in {"approve", "reject", "clarify"}:
        raise SessionStateError(
            code="invalid_review_decision",
            message="Review decision must be approve, reject, or clarify.",
            context={"decision": decision},
        )
    if decision == "clarify" and not message.strip():
        raise SessionStateError(
            code="clarify_requires_message",
            message="Clarify decisions require a non-empty review message.",
            context={"scope": scope},
        )

    decided_at = utc_now_iso()
    action_payload = {
        "decision": decision,
        "message": message,
        "decided_at": decided_at,
    }

    if scope == "prospect_research":
        current_action = session.prospect_research_review.action
        if current_action.decision == decision and current_action.message == message:
            return session
        prospect_research_review = session.prospect_research_review.model_copy(
            update={"action": HumanReviewAction(**action_payload)}
        )
        product_docs_review = session.product_docs_review
        company_understanding_review = session.company_understanding_review
    elif scope == "product_docs":
        current_action = session.product_docs_review.action
        if current_action.decision == decision and current_action.message == message:
            return session
        prospect_research_review = session.prospect_research_review
        product_docs_review = session.product_docs_review.model_copy(
            update={"action": HumanReviewAction(**action_payload)}
        )
        company_understanding_review = session.company_understanding_review
    else:
        if session.company_understanding_review is None:
            raise SessionStateError(
                code="missing_company_understanding_review",
                message="Session has no company-understanding review to update.",
                context={"session_id": session.session_id},
            )
        current_action = session.company_understanding_review.action
        if current_action.decision == decision and current_action.message == message:
            return session
        prospect_research_review = session.prospect_research_review
        product_docs_review = session.product_docs_review
        company_understanding_review = session.company_understanding_review.model_copy(
            update={"action": HumanReviewAction(**action_payload)}
        )

    updated_session = session.model_copy(
        update={
            "prospect_research_review": prospect_research_review,
            "product_docs_review": product_docs_review,
            "company_understanding_review": company_understanding_review,
            "updated_at": decided_at,
            "status": session_status(
                prospect_research_review,
                product_docs_review,
                company_understanding_review,
            ),
        }
    )
    save_session(updated_session)
    return updated_session
