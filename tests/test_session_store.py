from __future__ import annotations

import pytest

from email_sdr_flow.errors import SessionStateError
from email_sdr_flow.schemas import (
    CompanyUnderstanding,
    HumanReviewReport,
    ProductProfile,
    WorkflowSession,
)
from email_sdr_flow.session_store import (
    assert_resume_ready,
    default_checkpoint,
    load_session,
    save_session,
    update_review_session,
)


def _report(scope: str, requires_human_review: bool) -> HumanReviewReport:
    payload = {
        "scope": scope,
        "summary": f"{scope} summary",
        "requires_human_review": requires_human_review,
        "items": [],
    }
    if requires_human_review:
        payload["items"] = [
            {
                "category": "clarification_needed",
                "severity": "medium",
                "title": "Need clarification",
                "description": "Needs a human.",
                "affected_terms": [],
                "source_refs": [],
                "question_for_human": "Clarify this.",
            }
        ]
    return HumanReviewReport.model_validate(payload)


def _company_understanding() -> CompanyUnderstanding:
    return CompanyUnderstanding.model_validate(
        {
            "company_summary": "Summary",
            "business_model_hypothesis": "Model",
            "what_the_company_sells": "Software",
            "portfolio_shape": "single_product",
            "portfolio_complexity": "simple",
            "buyer_type_hypothesis": "business",
            "likely_gtm_motion": "sales_led",
            "likely_buyer_journey": "Journey",
            "likely_internal_teams": ["marketing"],
            "likely_existing_workflow": "Workflow",
            "likely_systems_or_handoffs": ["CRM"],
            "workflow_friction_points": ["Friction"],
            "volume_or_coordination_problem": "Problem",
            "product_layering_opportunities": [
                {
                    "workflow_step": "Step",
                    "target_team": "Marketing",
                    "current_motion": "Current",
                    "product_role": "Layer in",
                    "value_levers": ["conversion"],
                    "value_frame": "operational_leverage",
                    "support_level": "grounded",
                    "reasoning": "Because",
                }
            ],
            "value_levers": ["conversion"],
            "strongest_team_wedge": "Team wedge",
            "strongest_safe_wedge": "Safe wedge",
            "value_frame": "operational_leverage",
            "grounded_facts": ["Fact"],
            "workflow_hypotheses": ["Hypothesis"],
            "speculative_inferences": [],
            "ambiguities": [],
            "contradictions": [],
            "unsupported_assumptions": [],
            "overclaim_risks": [],
            "clarification_questions": ["Question?"],
            "outreach_implications": {
                "best_messaging_angle": "Angle",
                "anchor_pain": "Pain",
                "safe_proof_points": ["Proof"],
                "avoid_in_copy": ["Avoid"],
                "cta_style": "CTA",
                "angle_notes": [],
            },
        }
    )


def _session(tmp_path) -> WorkflowSession:
    from email_sdr_flow import session_store

    session_store.SESSIONS_DIR = tmp_path
    prospect = default_checkpoint(_report("prospect_research", True))
    product = default_checkpoint(_report("product_docs", False))
    company = default_checkpoint(_report("company_understanding", True))
    return WorkflowSession(
        session_id="abc123def456",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        status="pending_review",
        copywriting_dir="/tmp/copy",
        product_docs_dir="/tmp/product",
        product_profile=ProductProfile.model_validate(
            {
                "company_name": "Acme",
                "product_name": "Workflow Agent",
                "one_line_summary": "Summary",
            }
        ),
        raw_account_research={
            "account_name": "Acme",
            "target_persona_name": "Alex",
            "target_persona_role": "Head of Marketing",
        },
        prospect_research_review=prospect,
        product_docs_review=product,
        copywriting_snippets=[
            {
                "source_type": "copywriting",
                "title": "copy",
                "source_path": "/tmp/copy.md",
                "excerpt": "copy excerpt",
            }
        ],
        product_snippets=[
            {
                "source_type": "product_docs",
                "title": "product",
                "source_path": "/tmp/product.md",
                "excerpt": "product excerpt",
            }
        ],
        company_understanding=_company_understanding(),
        company_understanding_review=company,
    )


def test_update_review_session_requires_message_for_clarify(tmp_path):
    session = _session(tmp_path)

    with pytest.raises(SessionStateError) as exc_info:
        update_review_session(
            session,
            scope="company_understanding",
            decision="clarify",
            message="",
        )

    assert exc_info.value.code == "clarify_requires_message"


def test_assert_resume_ready_rejects_incomplete_session(tmp_path):
    session = _session(tmp_path).model_copy(
        update={"status": "ready_to_resume", "company_understanding": None}
    )

    with pytest.raises(SessionStateError) as exc_info:
        assert_resume_ready(session)

    assert exc_info.value.code == "session_missing_company_understanding"


def test_assert_resume_ready_requires_saved_grounding_snippets(tmp_path):
    session = _session(tmp_path).model_copy(
        update={"status": "ready_to_resume", "product_snippets": []}
    )

    with pytest.raises(SessionStateError) as exc_info:
        assert_resume_ready(session)

    assert exc_info.value.code == "session_missing_product_snippets"


def test_save_and_load_session_round_trip(tmp_path):
    session = _session(tmp_path)
    updated = update_review_session(
        session,
        scope="prospect_research",
        decision="clarify",
        message="Use the exact team name.",
    )
    updated = update_review_session(
        updated,
        scope="company_understanding",
        decision="approve",
        message="",
    )

    save_session(updated)
    loaded = load_session(updated.session_id)

    assert loaded.session_id == updated.session_id
    assert loaded.prospect_research_review.action.message == "Use the exact team name."


def test_completed_session_cannot_be_updated(tmp_path):
    session = _session(tmp_path).model_copy(update={"status": "completed"})

    with pytest.raises(SessionStateError) as exc_info:
        update_review_session(
            session,
            scope="product_docs",
            decision="approve",
            message="",
        )

    assert exc_info.value.code == "session_not_editable"


def test_load_session_rejects_unsupported_schema_version(tmp_path):
    from email_sdr_flow import session_store

    session_store.SESSIONS_DIR = tmp_path
    path = tmp_path / "abc123def456.json"
    path.write_text(
        """{
  "schema_version": 99,
  "session_id": "abc123def456",
  "created_at": "2026-01-01T00:00:00+00:00",
  "updated_at": "2026-01-01T00:00:00+00:00",
  "status": "completed",
  "copywriting_dir": "/tmp/copy",
  "product_docs_dir": "/tmp/product",
  "prospect_research_review": {
    "report": {
      "scope": "prospect_research",
      "summary": "ok",
      "requires_human_review": false,
      "items": []
    },
    "action": {
      "decision": "approve",
      "message": "ok",
      "decided_at": "2026-01-01T00:00:00+00:00"
    }
  },
  "product_docs_review": {
    "report": {
      "scope": "product_docs",
      "summary": "ok",
      "requires_human_review": false,
      "items": []
    },
    "action": {
      "decision": "approve",
      "message": "ok",
      "decided_at": "2026-01-01T00:00:00+00:00"
    }
  }
}""",
        encoding="utf-8",
    )

    with pytest.raises(SessionStateError) as exc_info:
        load_session("abc123def456")

    assert exc_info.value.code == "invalid_session_payload"
