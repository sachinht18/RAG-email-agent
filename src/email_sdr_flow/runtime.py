from __future__ import annotations

import logging
import os
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from email_sdr_flow.errors import StageExecutionError


LOGGER_NAME = "email_sdr_flow"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_STAGE_RETRIES = 1
DEFAULT_MODEL_TIMEOUT_SECONDS = 120.0
DEFAULT_MODEL_MAX_RETRIES = 2
T = TypeVar("T", bound=BaseModel)


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)


def configure_logging(level_name: str | None = None) -> None:
    level = getattr(
        logging,
        (level_name or os.getenv("EMAIL_SDR_LOG_LEVEL", DEFAULT_LOG_LEVEL)).upper(),
        logging.INFO,
    )
    logger = get_logger()
    if logger.handlers:
        logger.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.setLevel(level)


def log_event(event: str, **fields: Any) -> None:
    logger = get_logger()
    if fields:
        serialized = " ".join(
            f"{key}={fields[key]!r}" for key in sorted(fields) if fields[key] is not None
        )
        logger.info("%s %s", event, serialized)
    else:
        logger.info("%s", event)


def stage_retries() -> int:
    raw = os.getenv("EMAIL_SDR_STAGE_RETRIES", str(DEFAULT_STAGE_RETRIES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise StageExecutionError(
            code="invalid_stage_retries",
            message="EMAIL_SDR_STAGE_RETRIES must be an integer.",
            context={"value": raw},
        ) from exc
    return max(value, 0)


def model_timeout_seconds() -> float:
    raw = os.getenv("EMAIL_SDR_MODEL_TIMEOUT_SECONDS", str(DEFAULT_MODEL_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except ValueError as exc:
        raise StageExecutionError(
            code="invalid_model_timeout",
            message="EMAIL_SDR_MODEL_TIMEOUT_SECONDS must be numeric.",
            context={"value": raw},
        ) from exc
    if value <= 0:
        raise StageExecutionError(
            code="invalid_model_timeout",
            message="EMAIL_SDR_MODEL_TIMEOUT_SECONDS must be greater than zero.",
            context={"value": raw},
        )
    return value


def model_max_retries() -> int:
    raw = os.getenv("EMAIL_SDR_MODEL_MAX_RETRIES", str(DEFAULT_MODEL_MAX_RETRIES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise StageExecutionError(
            code="invalid_model_max_retries",
            message="EMAIL_SDR_MODEL_MAX_RETRIES must be an integer.",
            context={"value": raw},
        ) from exc
    return max(value, 0)


def validate_structured_output(raw: Any, schema: type[T], stage_name: str) -> T:
    if isinstance(raw, schema):
        return raw
    try:
        return schema.model_validate(raw)
    except ValidationError as exc:
        raise StageExecutionError(
            code="invalid_structured_output",
            message=f"{stage_name} returned data that did not match {schema.__name__}.",
            context={
                "stage": stage_name,
                "schema": schema.__name__,
                "validation_errors": exc.errors()[:5],
            },
        ) from exc


def invoke_structured_stage(
    *,
    stage_name: str,
    model: Any,
    schema: type[T],
    messages: list[tuple[str, str]],
) -> T:
    attempts = stage_retries() + 1
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        started_at = time.perf_counter()
        log_event("stage.start", stage=stage_name, attempt=attempt)
        try:
            raw = model.invoke(messages)
            parsed = validate_structured_output(raw, schema, stage_name)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            log_event(
                "stage.success",
                stage=stage_name,
                attempt=attempt,
                duration_ms=duration_ms,
            )
            return parsed
        except StageExecutionError as exc:
            last_error = exc
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            log_event(
                "stage.retryable_failure",
                stage=stage_name,
                attempt=attempt,
                duration_ms=duration_ms,
                code=exc.code,
            )
            if attempt >= attempts:
                raise
        except Exception as exc:
            last_error = exc
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            log_event(
                "stage.failure",
                stage=stage_name,
                attempt=attempt,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            if attempt >= attempts:
                raise StageExecutionError(
                    code="stage_invoke_failed",
                    message=f"{stage_name} failed during model invocation.",
                    context={
                        "stage": stage_name,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                ) from exc

    raise StageExecutionError(
        code="stage_unknown_failure",
        message=f"{stage_name} failed for an unknown reason.",
        context={"stage": stage_name, "last_error": str(last_error) if last_error else ""},
    )


def invoke_text_stage(
    *,
    stage_name: str,
    model: Any,
    messages: list[tuple[str, str]],
) -> str:
    started_at = time.perf_counter()
    log_event("stage.start", stage=stage_name)
    try:
        response = model.invoke(messages)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        log_event(
            "stage.failure",
            stage=stage_name,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
        )
        raise StageExecutionError(
            code="stage_invoke_failed",
            message=f"{stage_name} failed during model invocation.",
            context={"stage": stage_name, "error_type": type(exc).__name__, "error": str(exc)},
        ) from exc

    content = response.content
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    text = str(content).strip()
    if not text:
        raise StageExecutionError(
            code="empty_text_output",
            message=f"{stage_name} returned empty text output.",
            context={"stage": stage_name},
        )
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    log_event("stage.success", stage=stage_name, duration_ms=duration_ms)
    return text
