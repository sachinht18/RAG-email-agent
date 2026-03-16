from __future__ import annotations

from argparse import Namespace

import pytest

from email_sdr_flow.cli import _validate_args
from email_sdr_flow.errors import InputValidationError


def _args(**overrides) -> Namespace:
    payload = {
        "product_profile": None,
        "prospects_csv": None,
        "output_dir": None,
        "output_csv": None,
        "output_jsonl": None,
        "run_id": None,
        "overwrite_outputs": False,
        "fail_fast": False,
        "row_limit": None,
        "account_research": None,
        "raw_account_research": None,
        "copywriting_dir": None,
        "product_docs_dir": None,
        "hitl_only": False,
        "halt_on_hitl_findings": False,
        "create_session": False,
        "resume_session": None,
        "session_id": None,
        "review_scope": None,
        "review_decision": None,
        "review_message": "",
    }
    payload.update(overrides)
    return Namespace(**payload)


def test_validate_args_rejects_conflicting_single_run_inputs():
    with pytest.raises(InputValidationError) as exc_info:
        _validate_args(
            _args(account_research="account.json", raw_account_research="raw.json")
        )

    assert exc_info.value.code == "conflicting_single_run_inputs"


def test_validate_args_rejects_batch_only_flags_in_single_run_mode():
    with pytest.raises(InputValidationError) as exc_info:
        _validate_args(_args(raw_account_research="raw.json", row_limit=5))

    assert exc_info.value.code == "batch_only_argument"
