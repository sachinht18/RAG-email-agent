from __future__ import annotations

from email_sdr_flow.batch import (
    OUTPUT_FIELD_ORDER,
    append_batch_csv_row,
    build_batch_output_row,
)
from email_sdr_flow.schemas import RawAccountResearch


def _prospect() -> RawAccountResearch:
    return RawAccountResearch.model_validate(
        {
            "account_name": "Acme",
            "target_persona_name": "Jane Doe",
            "target_persona_role": "VP Marketing",
            "raw_recent_signals": ["Expanded into enterprise accounts."],
        }
    )


def test_build_batch_output_row_uses_concise_decision_trail_fields():
    row = build_batch_output_row(
        _prospect(),
        {
            "draft_strategy": {
                "messaging_angle": "Qualification quality for multi-step evaluation",
                "personalization_angle": "Expanded into enterprise accounts.",
                "chosen_pain_point": "Slow qualification",
                "value_hypothesis": "Speed up handoff",
                "proof_to_use": "Supports Salesforce and Slack routing",
                "cta_strategy": "Low friction",
            },
            "draft": {
                "subject_lines": ["Enterprise qualification without extra headcount"],
                "personalization_angle": "Expanded into enterprise accounts.",
                "opener": "opener",
                "pain_reframe": "pain",
                "value_prop": "value",
                "proof": "proof",
                "call_to_action": "cta",
                "email_body": "Hello, world",
            },
        },
    )

    assert list(row) == OUTPUT_FIELD_ORDER
    assert row["account_name"] == "Acme"
    assert row["persona"] == "Jane Doe (VP Marketing)"
    assert row["account_signal_used"] == "Expanded into enterprise accounts."
    assert row["product_proof_used"] == "Supports Salesforce and Slack routing"
    assert row["chosen_angle"] == "Qualification quality for multi-step evaluation"
    assert row["final_subject"] == "Enterprise qualification without extra headcount"
    assert row["final_draft"] == "Hello, world"
    assert row["status"] == "completed"


def test_append_batch_csv_row_writes_header_once_and_quotes_fields(tmp_path):
    path = tmp_path / "drafts.csv"
    row = {
        "account_name": "Acme",
        "persona": "Jane Doe (VP Marketing)",
        "account_signal_used": "Expanded into enterprise accounts.",
        "product_proof_used": "Supports Salesforce and Slack routing",
        "chosen_angle": "Qualification quality",
        "final_subject": "Enterprise qualification",
        "final_draft": "Hello, world",
        "status": "completed",
    }

    append_batch_csv_row(path, row)
    append_batch_csv_row(path, row)

    raw = path.read_text(encoding="utf-8").splitlines()
    assert raw[0] == ",".join(f'"{field}"' for field in OUTPUT_FIELD_ORDER)
    assert raw[1].endswith('"completed"')
    assert '"Hello, world"' in raw[1]
    assert len(raw) == 3
