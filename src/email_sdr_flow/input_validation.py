from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from email_sdr_flow.errors import ConfigurationError, InputValidationError, SessionStateError


SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def ensure_existing_file(path: Path, *, label: str, allowed_suffixes: set[str] | None = None) -> Path:
    if not path.exists():
        raise InputValidationError(
            code="missing_file",
            message=f"{label} file does not exist.",
            context={"path": str(path)},
        )
    if not path.is_file():
        raise InputValidationError(
            code="not_a_file",
            message=f"{label} path must point to a file.",
            context={"path": str(path)},
        )
    if allowed_suffixes and path.suffix.lower() not in allowed_suffixes:
        raise InputValidationError(
            code="unsupported_file_type",
            message=f"{label} must use one of the supported extensions.",
            context={"path": str(path), "allowed_suffixes": sorted(allowed_suffixes)},
        )
    return path


def ensure_existing_directory(path: Path, *, label: str) -> Path:
    if not path.exists():
        raise InputValidationError(
            code="missing_directory",
            message=f"{label} directory does not exist.",
            context={"path": str(path)},
        )
    if not path.is_dir():
        raise InputValidationError(
            code="not_a_directory",
            message=f"{label} path must point to a directory.",
            context={"path": str(path)},
        )
    return path


def load_json_file(path: Path, *, label: str) -> dict[str, Any]:
    ensure_existing_file(path, label=label, allowed_suffixes={".json"})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            code="invalid_json",
            message=f"{label} is not valid JSON.",
            context={"path": str(path), "line": exc.lineno, "column": exc.colno},
        ) from exc
    except UnicodeDecodeError as exc:
        raise InputValidationError(
            code="invalid_encoding",
            message=f"{label} could not be decoded as UTF-8.",
            context={"path": str(path)},
        ) from exc


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise SessionStateError(
            code="invalid_session_id",
            message="Session id must be a 12-character lowercase hexadecimal string.",
            context={"session_id": session_id},
        )
    return session_id


def ensure_parent_writable(path: Path, *, label: str, overwrite: bool = False) -> Path:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ConfigurationError(
            code="output_exists",
            message=f"{label} already exists. Choose a different path or enable overwrite.",
            context={"path": str(path)},
        )
    return path


def ensure_positive_int(value: int | None, *, label: str) -> int | None:
    if value is None:
        return None
    if value <= 0:
        raise ConfigurationError(
            code="invalid_positive_int",
            message=f"{label} must be greater than zero.",
            context={"value": value},
        )
    return value
