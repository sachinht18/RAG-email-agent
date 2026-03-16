from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypedDict

from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph

from email_sdr_flow.prompts import (
    COMPANY_UNDERSTANDING_HITL_REVIEWER_SYSTEM_PROMPT,
    COMPANY_UNDERSTANDING_SYSTEM_PROMPT,
    COPYWRITING_QUERY_PLANNER_SYSTEM_PROMPT,
    COPY_REVIEWER_SYSTEM_PROMPT,
    DRAFTER_SYSTEM_PROMPT,
    FINAL_REASONER_SYSTEM_PROMPT,
    GROUNDING_REVIEWER_SYSTEM_PROMPT,
    PRODUCT_DOC_HITL_REVIEWER_SYSTEM_PROMPT,
    PRODUCT_QUERY_PLANNER_SYSTEM_PROMPT,
    PROSPECT_HITL_REVIEWER_SYSTEM_PROMPT,
    RESEARCH_NORMALIZER_SYSTEM_PROMPT,
    RESEARCH_PLANNER_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
)
from email_sdr_flow.errors import ConfigurationError, StageExecutionError
from email_sdr_flow.retrieval import (
    KnowledgeBase,
    build_knowledge_base,
    docs_to_snippets,
    format_documents_for_review,
    format_snippets,
    load_source_documents,
    retrieve_documents,
)
from email_sdr_flow.runtime import (
    invoke_structured_stage,
    invoke_text_stage,
    log_event,
    model_max_retries,
    model_timeout_seconds,
)
from email_sdr_flow.schemas import (
    AccountResearch,
    CompanyUnderstanding,
    DraftStrategy,
    EmailDraft,
    GroundingSnippet,
    HumanReviewReport,
    ProductProfile,
    RawAccountResearch,
    ResearchPlan,
    RetrievalPlan,
    ReviewResult,
    WorkflowSession,
)
from email_sdr_flow.session_store import (
    assert_resume_ready,
    default_checkpoint,
    generate_session_id,
    save_session,
    session_status,
    utc_now_iso,
)


ROLE_DEFAULTS = {
    "QUERY_PLANNER": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "STRATEGIST": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "DRAFTER": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "GROUNDING_REVIEWER": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "COPY_REVIEWER": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "FINAL_REASONER": {
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "EMBEDDINGS": {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "api_key_env": "OPENAI_API_KEY",
    },
    "RESEARCH_PLANNER": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "RESEARCH_NORMALIZER": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "HITL_REVIEWER": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "COMPANY_UNDERSTANDING": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
}


class FlowState(TypedDict, total=False):
    product_profile: ProductProfile
    raw_account_research: RawAccountResearch
    research_plan: ResearchPlan
    prospect_research_review: HumanReviewReport
    product_docs_review: HumanReviewReport
    company_understanding_review: HumanReviewReport | None
    halted_for_human_review: bool
    human_review_context: list[str]
    account_research: AccountResearch
    revision_count: int
    copywriting_kb_diagnostics: dict[str, Any]
    product_kb_diagnostics: dict[str, Any]
    copywriting_retrieval_diagnostics: dict[str, Any]
    product_retrieval_diagnostics: dict[str, Any]
    copywriting_query: str
    product_query: str
    copywriting_snippets: list[GroundingSnippet]
    product_snippets: list[GroundingSnippet]
    company_understanding: CompanyUnderstanding
    draft_strategy: DraftStrategy
    draft: EmailDraft
    grounding_review: ReviewResult
    copy_review: ReviewResult
    final_reasoning_notes: str


class FlowDependencies(TypedDict, total=False):
    copywriting_kb: KnowledgeBase
    product_kb: KnowledgeBase
    hitl_reviewer_model: Any
    company_understanding_model: Any
    research_planner_model: Any
    research_normalizer_model: Any
    copywriting_query_planner_model: Any
    product_query_planner_model: Any
    strategist_model: Any
    drafter_model: Any
    grounding_reviewer_model: Any
    copy_reviewer_model: Any
    final_reasoner_model: Any


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigurationError(
            code="missing_env_var",
            message="Required environment variable is not set.",
            context={"env_var": name},
        )
    return value


def _get_role_setting(role: str, key: str) -> str:
    env_name = f"EMAIL_SDR_{role}_{key}".upper()
    return os.getenv(env_name, ROLE_DEFAULTS[role][key.lower()])


def _build_chat_model(
    role: str,
    *,
    temperature: float,
    structured_required: bool = False,
) -> Any:
    provider = _get_role_setting(role, "PROVIDER").lower()
    model = _get_role_setting(role, "MODEL")
    api_key_env = _get_role_setting(role, "API_KEY_ENV")

    if structured_required and provider == "deepseek" and model == "deepseek-reasoner":
        raise ConfigurationError(
            code="invalid_model_for_structured_stage",
            message=(
                f"{role} uses deepseek-reasoner, but this node requires structured output. "
                "Use deepseek-chat for this role."
            ),
            context={"role": role, "model": model},
        )

    if provider == "deepseek":
        base_url = os.getenv(
            f"EMAIL_SDR_{role}_BASE_URL".upper(),
            "https://api.deepseek.com",
        )
        return ChatDeepSeek(
            model=model,
            temperature=temperature,
            api_key=_require_env(api_key_env),
            base_url=base_url,
            timeout=model_timeout_seconds(),
            max_retries=model_max_retries(),
        )

    if provider == "openai":
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=_require_env(api_key_env),
            base_url=os.getenv(f"EMAIL_SDR_{role}_BASE_URL".upper()),
            timeout=model_timeout_seconds(),
            max_retries=model_max_retries(),
        )

    raise ConfigurationError(
        code="unsupported_provider",
        message="Role provider is not supported.",
        context={"role": role, "provider": provider},
    )


def _build_embeddings() -> OpenAIEmbeddings:
    provider = _get_role_setting("EMBEDDINGS", "PROVIDER").lower()
    model = _get_role_setting("EMBEDDINGS", "MODEL")
    api_key_env = _get_role_setting("EMBEDDINGS", "API_KEY_ENV")

    if provider != "openai":
        raise ConfigurationError(
            code="unsupported_embeddings_provider",
            message=(
                "This framework currently supports OpenAI-compatible embeddings only. "
                "Set EMAIL_SDR_EMBEDDINGS_PROVIDER=openai."
            ),
            context={"provider": provider},
        )

    return OpenAIEmbeddings(
        model=model,
        api_key=_require_env(api_key_env),
        base_url=os.getenv("EMAIL_SDR_EMBEDDINGS_BASE_URL"),
        timeout=model_timeout_seconds(),
        max_retries=model_max_retries(),
    )


def _structured_model(model: Any, schema: Any) -> Any:
    if isinstance(model, ChatDeepSeek):
        return model.with_structured_output(schema, method="json_mode")
    return model.with_structured_output(schema)


def _require_dependency(deps: FlowDependencies, key: str) -> Any:
    if key not in deps:
        raise ConfigurationError(
            code="missing_dependency",
            message="Workflow dependency was not initialized.",
            context={"dependency": key},
        )
    return deps[key]


def _account_research_payload(account_research: AccountResearch) -> str:
    return json.dumps(account_research.model_dump(), indent=2)


def _product_profile_payload(product_profile: ProductProfile) -> str:
    return json.dumps(product_profile.model_dump(), indent=2)


def _raw_account_research_payload(raw_account_research: RawAccountResearch) -> str:
    return json.dumps(raw_account_research.model_dump(), indent=2)


def _rewrite_brief(state: FlowState) -> str:
    reviews = []
    grounding_review = state.get("grounding_review")
    copy_review = state.get("copy_review")

    if grounding_review and not grounding_review.approved and grounding_review.rewrite_brief:
        reviews.append(f"Grounding fixes:\n{grounding_review.rewrite_brief}")
    if copy_review and not copy_review.approved and copy_review.rewrite_brief:
        reviews.append(f"Copy fixes:\n{copy_review.rewrite_brief}")

    return "\n\n".join(reviews)


def _format_human_review_context(state: FlowState) -> str:
    context = state.get("human_review_context", [])
    if not context:
        return ""
    return "\n\nHuman review guidance:\n" + "\n".join(f"- {item}" for item in context)


def _build_prospect_hitl_messages(
    raw_or_normalized_payload: str,
    product_profile: ProductProfile,
) -> list[tuple[str, str]]:
    return [
        ("system", PROSPECT_HITL_REVIEWER_SYSTEM_PROMPT),
        (
            "human",
            "Review this prospect research material and surface human-review issues.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"{raw_or_normalized_payload}",
        ),
    ]


def _build_product_docs_hitl_messages(
    formatted_documents: str,
    product_profile: ProductProfile,
) -> list[tuple[str, str]]:
    return [
        ("system", PRODUCT_DOC_HITL_REVIEWER_SYSTEM_PROMPT),
        (
            "human",
            "Review these ingested product-document excerpts and surface human-review issues.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"{formatted_documents}",
        ),
    ]


def _build_research_plan_messages(
    raw_account_research: RawAccountResearch,
    product_profile: ProductProfile,
) -> list[tuple[str, str]]:
    return [
        ("system", RESEARCH_PLANNER_SYSTEM_PROMPT),
        (
            "human",
            "Review this raw account dossier and produce a research plan.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"Raw account dossier:\n{_raw_account_research_payload(raw_account_research)}",
        ),
    ]


def _build_company_understanding_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", COMPANY_UNDERSTANDING_SYSTEM_PROMPT),
        (
            "human",
            "Build the company-understanding and workflow-mapping artifact.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Product documentation context:\n{format_snippets(state['product_snippets'])}"
            f"{_format_human_review_context(state)}",
        ),
    ]


def _build_company_understanding_hitl_messages(
    company_understanding: CompanyUnderstanding,
    product_profile: ProductProfile,
    account_research: AccountResearch,
) -> list[tuple[str, str]]:
    return [
        ("system", COMPANY_UNDERSTANDING_HITL_REVIEWER_SYSTEM_PROMPT),
        (
            "human",
            "Review this company-understanding artifact and surface human-review issues.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"Account research:\n{_account_research_payload(account_research)}\n\n"
            f"Company understanding:\n{json.dumps(company_understanding.model_dump(), indent=2)}",
        ),
    ]


def _human_review_required(*reports: HumanReviewReport | None) -> bool:
    return any(report is not None and report.requires_human_review for report in reports)


def _apply_product_defaults(
    *,
    product_profile: ProductProfile,
    raw_account_research: RawAccountResearch | None = None,
    account_research: AccountResearch | None = None,
) -> tuple[RawAccountResearch | None, AccountResearch | None]:
    default_cta = "Open to a 15-minute conversation next week?"
    if raw_account_research is not None and raw_account_research.desired_cta == default_cta:
        raw_account_research = raw_account_research.model_copy(
            update={"desired_cta": product_profile.default_cta}
        )
    if account_research is not None and account_research.desired_cta == default_cta:
        account_research = account_research.model_copy(
            update={"desired_cta": product_profile.default_cta}
        )
    return raw_account_research, account_research


def analyze_product_docs(
    *,
    product_docs_dir: str | Path,
    product_profile: ProductProfile,
    reviewer_model: Any,
) -> HumanReviewReport:
    documents = load_source_documents(product_docs_dir, source_type="product_docs")
    reviewer = _structured_model(reviewer_model, HumanReviewReport)
    report = invoke_structured_stage(
        stage_name="product_docs_hitl_review",
        model=reviewer,
        schema=HumanReviewReport,
        messages=_build_product_docs_hitl_messages(
            format_documents_for_review(documents),
            product_profile,
        ),
    )
    return report.model_copy(update={"scope": "product_docs"})


def analyze_prospect_research(
    *,
    product_profile: ProductProfile,
    reviewer_model: Any,
    raw_account_research: RawAccountResearch | None = None,
    account_research: AccountResearch | None = None,
) -> HumanReviewReport:
    if raw_account_research is not None:
        payload = (
            "Scope: raw prospect research\n\n"
            f"{_raw_account_research_payload(raw_account_research)}"
        )
    elif account_research is not None:
        payload = (
            "Scope: normalized prospect research\n\n"
            f"{_account_research_payload(account_research)}"
        )
    else:
        raise StageExecutionError(
            code="missing_prospect_review_input",
            message="Prospect review requires raw_account_research or account_research.",
            context={},
        )

    reviewer = _structured_model(reviewer_model, HumanReviewReport)
    report = invoke_structured_stage(
        stage_name="prospect_hitl_review",
        model=reviewer,
        schema=HumanReviewReport,
        messages=_build_prospect_hitl_messages(payload, product_profile),
    )
    return report.model_copy(update={"scope": "prospect_research"})


def analyze_company_understanding(
    *,
    reviewer_model: Any,
    product_profile: ProductProfile,
    account_research: AccountResearch,
    company_understanding: CompanyUnderstanding,
) -> HumanReviewReport:
    reviewer = _structured_model(reviewer_model, HumanReviewReport)
    report = invoke_structured_stage(
        stage_name="company_understanding_hitl_review",
        model=reviewer,
        schema=HumanReviewReport,
        messages=_build_company_understanding_hitl_messages(
            company_understanding,
            product_profile,
            account_research,
        ),
    )
    return report.model_copy(update={"scope": "company_understanding"})


def _human_review_context_from_session(session: WorkflowSession) -> list[str]:
    context: list[str] = []
    checkpoints = [
        ("prospect research", session.prospect_research_review),
        ("product docs", session.product_docs_review),
    ]
    if session.company_understanding_review is not None:
        checkpoints.append(
            ("company understanding", session.company_understanding_review)
        )
    for label, checkpoint in checkpoints:
        if checkpoint.action.decision in {"approve", "clarify"} and checkpoint.action.message:
            context.append(f"{label}: {checkpoint.action.message}")
    return context


def _prepare_company_understanding_state(
    *,
    dependencies: FlowDependencies,
    product_docs_dir: str | Path,
    product_profile: ProductProfile,
    raw_account_research: RawAccountResearch | None = None,
    account_research: AccountResearch | None = None,
    human_review_context: list[str] | None = None,
    product_docs_review: HumanReviewReport | None = None,
    prospect_research_review: HumanReviewReport | None = None,
) -> FlowState:
    raw_account_research, account_research = _apply_product_defaults(
        product_profile=product_profile,
        raw_account_research=raw_account_research,
        account_research=account_research,
    )
    if product_docs_review is None:
        product_docs_review = analyze_product_docs(
            product_docs_dir=product_docs_dir,
            product_profile=product_profile,
            reviewer_model=_require_dependency(dependencies, "hitl_reviewer_model"),
        )
    if prospect_research_review is None:
        prospect_research_review = analyze_prospect_research(
            product_profile=product_profile,
            reviewer_model=_require_dependency(dependencies, "hitl_reviewer_model"),
            raw_account_research=raw_account_research,
            account_research=account_research,
        )

    state: FlowState = {
        "product_profile": product_profile,
        "revision_count": 0,
        "product_docs_review": product_docs_review,
        "prospect_research_review": prospect_research_review,
        "halted_for_human_review": False,
        "copywriting_kb_diagnostics": _require_dependency(
            dependencies, "copywriting_kb"
        ).diagnostics.to_dict(),
        "product_kb_diagnostics": _require_dependency(
            dependencies, "product_kb"
        ).diagnostics.to_dict(),
    }
    if human_review_context:
        state["human_review_context"] = human_review_context
    if raw_account_research is not None:
        state["raw_account_research"] = raw_account_research
    if account_research is not None:
        state["account_research"] = account_research

    research_planner = _structured_model(
        _require_dependency(dependencies, "research_planner_model"),
        ResearchPlan,
    )
    research_normalizer = _structured_model(
        _require_dependency(dependencies, "research_normalizer_model"),
        AccountResearch,
    )
    copywriting_query_planner = _structured_model(
        _require_dependency(dependencies, "copywriting_query_planner_model"),
        RetrievalPlan,
    )
    product_query_planner = _structured_model(
        _require_dependency(dependencies, "product_query_planner_model"),
        RetrievalPlan,
    )
    company_understanding_builder = _structured_model(
        _require_dependency(dependencies, "company_understanding_model"),
        CompanyUnderstanding,
    )

    if state.get("account_research") is None:
        if raw_account_research is None:
            raise StageExecutionError(
                code="missing_preparation_input",
                message="Pre-draft preparation requires account_research or raw_account_research.",
                context={},
            )
        research_plan = invoke_structured_stage(
            stage_name="research_planning",
            model=research_planner,
            schema=ResearchPlan,
            messages=_build_research_plan_messages(raw_account_research, product_profile),
        )
        state["research_plan"] = research_plan
        state["account_research"] = invoke_structured_stage(
            stage_name="research_normalization",
            model=research_normalizer,
            schema=AccountResearch,
            messages=_build_research_normalizer_messages(state),
        )

    copywriting_plan = invoke_structured_stage(
        stage_name="copywriting_query_planning",
        model=copywriting_query_planner,
        schema=RetrievalPlan,
        messages=_build_copywriting_query_messages(
            state["account_research"],
            product_profile,
        ),
    )
    product_plan = invoke_structured_stage(
        stage_name="product_query_planning",
        model=product_query_planner,
        schema=RetrievalPlan,
        messages=_build_product_query_messages(
            state["account_research"],
            product_profile,
        ),
    )
    state["copywriting_query"] = copywriting_plan.query
    state["product_query"] = product_plan.query

    copywriting_docs, copywriting_retrieval = retrieve_documents(
        _require_dependency(dependencies, "copywriting_kb"),
        state["copywriting_query"],
    )
    product_docs, product_retrieval = retrieve_documents(
        _require_dependency(dependencies, "product_kb"),
        state["product_query"],
    )
    state["copywriting_retrieval_diagnostics"] = copywriting_retrieval.to_dict()
    state["product_retrieval_diagnostics"] = product_retrieval.to_dict()
    state["copywriting_snippets"] = docs_to_snippets(copywriting_docs)
    state["product_snippets"] = docs_to_snippets(product_docs)

    company_understanding = invoke_structured_stage(
        stage_name="company_understanding",
        model=company_understanding_builder,
        schema=CompanyUnderstanding,
        messages=_build_company_understanding_messages(state),
    )
    state["company_understanding"] = company_understanding
    state["company_understanding_review"] = analyze_company_understanding(
        reviewer_model=_require_dependency(dependencies, "hitl_reviewer_model"),
        product_profile=product_profile,
        account_research=state["account_research"],
        company_understanding=company_understanding,
    )
    return state


def create_review_session(
    *,
    copywriting_dir: str | Path,
    product_docs_dir: str | Path,
    product_profile: ProductProfile,
    raw_account_research: RawAccountResearch | None = None,
    account_research: AccountResearch | None = None,
) -> WorkflowSession:
    log_event("session.create_start")
    dependencies = build_default_dependencies(
        copywriting_dir=copywriting_dir,
        product_docs_dir=product_docs_dir,
        required_roles={
            "HITL_REVIEWER",
            "RESEARCH_PLANNER",
            "RESEARCH_NORMALIZER",
            "QUERY_PLANNER",
            "COMPANY_UNDERSTANDING",
        },
    )
    prepared_state = _prepare_company_understanding_state(
        dependencies=dependencies,
        product_docs_dir=product_docs_dir,
        product_profile=product_profile,
        raw_account_research=raw_account_research,
        account_research=account_research,
    )

    created_at = utc_now_iso()
    session = WorkflowSession(
        session_id=generate_session_id(),
        created_at=created_at,
        updated_at=created_at,
        status="pending_review",
        copywriting_dir=str(copywriting_dir),
        product_docs_dir=str(product_docs_dir),
        product_profile=product_profile,
        raw_account_research=prepared_state.get("raw_account_research"),
        account_research=prepared_state.get("account_research"),
        research_plan=prepared_state.get("research_plan"),
        copywriting_query=prepared_state.get("copywriting_query"),
        product_query=prepared_state.get("product_query"),
        copywriting_retrieval_diagnostics=prepared_state.get(
            "copywriting_retrieval_diagnostics", {}
        ),
        product_retrieval_diagnostics=prepared_state.get(
            "product_retrieval_diagnostics", {}
        ),
        copywriting_snippets=prepared_state.get("copywriting_snippets", []),
        product_snippets=prepared_state.get("product_snippets", []),
        company_understanding=prepared_state.get("company_understanding"),
        prospect_research_review=default_checkpoint(
            prepared_state["prospect_research_review"]
        ),
        product_docs_review=default_checkpoint(prepared_state["product_docs_review"]),
        company_understanding_review=default_checkpoint(
            prepared_state["company_understanding_review"]
        ),
    )
    session = session.model_copy(
        update={
            "status": session_status(
                session.prospect_research_review,
                session.product_docs_review,
                session.company_understanding_review,
            )
        }
    )
    save_session(session)
    log_event("session.create_complete", session_id=session.session_id, status=session.status)
    return session


def resume_review_session(session: WorkflowSession) -> FlowState:
    assert_resume_ready(session)
    log_event("session.resume_start", session_id=session.session_id)

    dependencies = build_default_dependencies(
        copywriting_dir=session.copywriting_dir,
        product_docs_dir=session.product_docs_dir,
        required_roles={
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
    app = build_email_sdr_flow(dependencies)
    initial_state: FlowState = {
        "product_profile": session.product_profile,
        "revision_count": 0,
        "copywriting_kb_diagnostics": _require_dependency(
            dependencies, "copywriting_kb"
        ).diagnostics.to_dict(),
        "product_kb_diagnostics": _require_dependency(
            dependencies, "product_kb"
        ).diagnostics.to_dict(),
        "product_docs_review": session.product_docs_review.report,
        "prospect_research_review": session.prospect_research_review.report,
        "halted_for_human_review": False,
        "human_review_context": _human_review_context_from_session(session),
    }
    if session.company_understanding_review is not None:
        initial_state["company_understanding_review"] = (
            session.company_understanding_review.report
        )
    if session.research_plan is not None:
        initial_state["research_plan"] = session.research_plan
    if session.account_research is not None:
        initial_state["account_research"] = session.account_research
    if session.raw_account_research is not None:
        initial_state["raw_account_research"] = session.raw_account_research
    if session.copywriting_query is not None:
        initial_state["copywriting_query"] = session.copywriting_query
    if session.product_query is not None:
        initial_state["product_query"] = session.product_query
    if session.copywriting_retrieval_diagnostics:
        initial_state["copywriting_retrieval_diagnostics"] = (
            session.copywriting_retrieval_diagnostics
        )
    if session.product_retrieval_diagnostics:
        initial_state["product_retrieval_diagnostics"] = (
            session.product_retrieval_diagnostics
        )
    if session.copywriting_snippets:
        initial_state["copywriting_snippets"] = session.copywriting_snippets
    if session.product_snippets:
        initial_state["product_snippets"] = session.product_snippets
    if session.company_understanding is not None:
        initial_state["company_understanding"] = session.company_understanding

    result = app.invoke(initial_state)
    completed_session = session.model_copy(
        update={
            "updated_at": utc_now_iso(),
            "status": "completed",
            "result_snapshot": {
                key: value.model_dump() if hasattr(value, "model_dump") else value
                for key, value in result.items()
            },
        }
    )
    save_session(completed_session)
    log_event("session.resume_complete", session_id=session.session_id)
    return result


def _build_research_normalizer_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", RESEARCH_NORMALIZER_SYSTEM_PROMPT),
        (
            "human",
            "Normalize this raw account dossier into the strict account research schema.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Raw account dossier:\n{_raw_account_research_payload(state['raw_account_research'])}\n\n"
            f"Research plan:\n{json.dumps(state['research_plan'].model_dump(), indent=2)}"
            f"{_format_human_review_context(state)}",
        ),
    ]


def _build_copywriting_query_messages(
    account_research: AccountResearch,
    product_profile: ProductProfile,
) -> list[tuple[str, str]]:
    return [
        ("system", COPYWRITING_QUERY_PLANNER_SYSTEM_PROMPT),
        (
            "human",
            "Plan the best retrieval query for copywriting and positioning guidance.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"Account research:\n{_account_research_payload(account_research)}",
        ),
    ]


def _build_product_query_messages(
    account_research: AccountResearch,
    product_profile: ProductProfile,
) -> list[tuple[str, str]]:
    return [
        ("system", PRODUCT_QUERY_PLANNER_SYSTEM_PROMPT),
        (
            "human",
            "Plan the best retrieval query for product documentation.\n\n"
            f"Product profile:\n{_product_profile_payload(product_profile)}\n\n"
            f"Account research:\n{_account_research_payload(account_research)}",
        ),
    ]


def _build_strategy_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", STRATEGIST_SYSTEM_PROMPT),
        (
            "human",
            "Choose the email strategy.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Company understanding:\n{json.dumps(state['company_understanding'].model_dump(), indent=2)}\n\n"
            f"Copywriting context:\n{format_snippets(state['copywriting_snippets'])}\n\n"
            f"Product documentation context:\n{format_snippets(state['product_snippets'])}"
            f"{_format_human_review_context(state)}",
        ),
    ]


def _build_drafter_messages(state: FlowState) -> list[tuple[str, str]]:
    rewrite_brief = _rewrite_brief(state)
    rewrite_section = f"\n\nRevision instruction:\n{rewrite_brief}" if rewrite_brief else ""
    return [
        ("system", DRAFTER_SYSTEM_PROMPT),
        (
            "human",
            "Draft one SDR email package.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Company understanding:\n{json.dumps(state['company_understanding'].model_dump(), indent=2)}\n\n"
            f"Draft strategy:\n{json.dumps(state['draft_strategy'].model_dump(), indent=2)}\n\n"
            f"Copywriting context:\n{format_snippets(state['copywriting_snippets'])}\n\n"
            f"Product documentation context:\n{format_snippets(state['product_snippets'])}"
            f"{_format_human_review_context(state)}"
            f"{rewrite_section}",
        ),
    ]


def _build_grounding_review_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", GROUNDING_REVIEWER_SYSTEM_PROMPT),
        (
            "human",
            "Review this draft only for factual grounding.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Company understanding:\n{json.dumps(state['company_understanding'].model_dump(), indent=2)}\n\n"
            f"Product documentation context:\n{format_snippets(state['product_snippets'])}\n\n"
            f"Draft:\n{json.dumps(state['draft'].model_dump(), indent=2)}",
        ),
    ]


def _build_copy_review_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", COPY_REVIEWER_SYSTEM_PROMPT),
        (
            "human",
            "Review this draft for copy quality and positioning.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Company understanding:\n{json.dumps(state['company_understanding'].model_dump(), indent=2)}\n\n"
            f"Copywriting context:\n{format_snippets(state['copywriting_snippets'])}\n\n"
            f"Draft:\n{json.dumps(state['draft'].model_dump(), indent=2)}",
        ),
    ]


def _build_final_reasoner_messages(state: FlowState) -> list[tuple[str, str]]:
    return [
        ("system", FINAL_REASONER_SYSTEM_PROMPT),
        (
            "human",
            "Provide the final reasoning critique.\n\n"
            f"Product profile:\n{_product_profile_payload(state['product_profile'])}\n\n"
            f"Account research:\n{_account_research_payload(state['account_research'])}\n\n"
            f"Company understanding:\n{json.dumps(state['company_understanding'].model_dump(), indent=2)}\n\n"
            f"Draft strategy:\n{json.dumps(state['draft_strategy'].model_dump(), indent=2)}\n\n"
            f"Product documentation context:\n{format_snippets(state['product_snippets'])}\n\n"
            f"Copywriting context:\n{format_snippets(state['copywriting_snippets'])}\n\n"
            f"Grounding review:\n{json.dumps(state['grounding_review'].model_dump(), indent=2)}\n\n"
            f"Copy review:\n{json.dumps(state['copy_review'].model_dump(), indent=2)}\n\n"
            f"Draft:\n{json.dumps(state['draft'].model_dump(), indent=2)}",
        ),
    ]


def build_email_sdr_flow(deps: FlowDependencies):
    research_planner = _structured_model(
        _require_dependency(deps, "research_planner_model"),
        ResearchPlan,
    )
    research_normalizer = _structured_model(
        _require_dependency(deps, "research_normalizer_model"),
        AccountResearch,
    )
    copywriting_query_planner = _structured_model(
        _require_dependency(deps, "copywriting_query_planner_model"),
        RetrievalPlan,
    )
    product_query_planner = _structured_model(
        _require_dependency(deps, "product_query_planner_model"),
        RetrievalPlan,
    )
    company_understanding_builder = _structured_model(
        _require_dependency(deps, "company_understanding_model"),
        CompanyUnderstanding,
    )
    strategist = _structured_model(_require_dependency(deps, "strategist_model"), DraftStrategy)
    drafter = _structured_model(_require_dependency(deps, "drafter_model"), EmailDraft)
    grounding_reviewer = _structured_model(
        _require_dependency(deps, "grounding_reviewer_model"),
        ReviewResult,
    )
    copy_reviewer = _structured_model(_require_dependency(deps, "copy_reviewer_model"), ReviewResult)
    final_reasoner = _require_dependency(deps, "final_reasoner_model")

    def route_start(state: FlowState) -> str:
        if state.get("product_profile") is None:
            raise StageExecutionError(
                code="missing_product_profile",
                message="Flow requires a product_profile input.",
                context={},
            )
        if (
            state.get("account_research") is not None
            and state.get("company_understanding") is not None
            and state.get("copywriting_snippets") is not None
            and state.get("product_snippets") is not None
        ):
            return "ready_for_strategy"
        if state.get("account_research") is not None:
            return "normalized_input"
        if state.get("raw_account_research") is not None:
            return "raw_input"
        raise StageExecutionError(
            code="missing_flow_input",
            message="Flow requires either account_research or raw_account_research as input.",
            context={},
        )

    def plan_research(state: FlowState) -> FlowState:
        plan = invoke_structured_stage(
            stage_name="research_planning",
            model=research_planner,
            schema=ResearchPlan,
            messages=_build_research_plan_messages(
                state["raw_account_research"],
                state["product_profile"],
            ),
        )
        return {"research_plan": plan}

    def normalize_research(state: FlowState) -> FlowState:
        normalized = invoke_structured_stage(
            stage_name="research_normalization",
            model=research_normalizer,
            schema=AccountResearch,
            messages=_build_research_normalizer_messages(state),
        )
        return {"account_research": normalized}

    def dispatch_queries(_: FlowState) -> FlowState:
        return {}

    def plan_copywriting_query(state: FlowState) -> FlowState:
        plan = invoke_structured_stage(
            stage_name="copywriting_query_planning",
            model=copywriting_query_planner,
            schema=RetrievalPlan,
            messages=_build_copywriting_query_messages(
                state["account_research"],
                state["product_profile"],
            ),
        )
        return {"copywriting_query": plan.query}

    def plan_product_query(state: FlowState) -> FlowState:
        plan = invoke_structured_stage(
            stage_name="product_query_planning",
            model=product_query_planner,
            schema=RetrievalPlan,
            messages=_build_product_query_messages(
                state["account_research"],
                state["product_profile"],
            ),
        )
        return {"product_query": plan.query}

    def retrieve_copywriting(state: FlowState) -> FlowState:
        docs, diagnostics = retrieve_documents(
            _require_dependency(deps, "copywriting_kb"),
            state["copywriting_query"],
        )
        return {
            "copywriting_snippets": docs_to_snippets(docs),
            "copywriting_retrieval_diagnostics": diagnostics.to_dict(),
        }

    def retrieve_product_docs(state: FlowState) -> FlowState:
        docs, diagnostics = retrieve_documents(
            _require_dependency(deps, "product_kb"),
            state["product_query"],
        )
        return {
            "product_snippets": docs_to_snippets(docs),
            "product_retrieval_diagnostics": diagnostics.to_dict(),
        }

    def build_company_understanding(state: FlowState) -> FlowState:
        understanding = invoke_structured_stage(
            stage_name="company_understanding",
            model=company_understanding_builder,
            schema=CompanyUnderstanding,
            messages=_build_company_understanding_messages(state),
        )
        return {"company_understanding": understanding}

    def build_strategy(state: FlowState) -> FlowState:
        strategy = invoke_structured_stage(
            stage_name="draft_strategy",
            model=strategist,
            schema=DraftStrategy,
            messages=_build_strategy_messages(state),
        )
        return {"draft_strategy": strategy}

    def draft_email(state: FlowState) -> FlowState:
        draft = invoke_structured_stage(
            stage_name="draft_email",
            model=drafter,
            schema=EmailDraft,
            messages=_build_drafter_messages(state),
        )
        return {"draft": draft}

    def review_grounding(state: FlowState) -> FlowState:
        review = invoke_structured_stage(
            stage_name="grounding_review",
            model=grounding_reviewer,
            schema=ReviewResult,
            messages=_build_grounding_review_messages(state),
        )
        return {"grounding_review": review}

    def review_copy(state: FlowState) -> FlowState:
        review = invoke_structured_stage(
            stage_name="copy_review",
            model=copy_reviewer,
            schema=ReviewResult,
            messages=_build_copy_review_messages(state),
        )
        return {"copy_review": review}

    def mark_revision(state: FlowState) -> FlowState:
        return {"revision_count": state.get("revision_count", 0) + 1}

    def join_reviews(_: FlowState) -> FlowState:
        return {}

    def route_after_reviews(state: FlowState) -> str:
        grounding_ok = state["grounding_review"].approved
        copy_ok = state["copy_review"].approved
        if grounding_ok and copy_ok:
            return "final_reasoning"
        if state.get("revision_count", 0) >= 1:
            return "final_reasoning"
        return "revise"

    def final_reasoning(state: FlowState) -> FlowState:
        return {
            "final_reasoning_notes": invoke_text_stage(
                stage_name="final_reasoning",
                model=final_reasoner,
                messages=_build_final_reasoner_messages(state),
            )
        }

    graph = StateGraph(FlowState)
    graph.add_node("plan_research", plan_research)
    graph.add_node("normalize_research", normalize_research)
    graph.add_node("dispatch_queries", dispatch_queries)
    graph.add_node("plan_copywriting_query", plan_copywriting_query)
    graph.add_node("plan_product_query", plan_product_query)
    graph.add_node("retrieve_copywriting", retrieve_copywriting)
    graph.add_node("retrieve_product_docs", retrieve_product_docs)
    graph.add_node("build_company_understanding", build_company_understanding)
    graph.add_node("build_strategy", build_strategy)
    graph.add_node("draft_email", draft_email)
    graph.add_node("review_grounding", review_grounding)
    graph.add_node("review_copy", review_copy)
    graph.add_node("join_reviews", join_reviews)
    graph.add_node("mark_revision", mark_revision)
    graph.add_node("final_reasoning", final_reasoning)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "raw_input": "plan_research",
            "normalized_input": "dispatch_queries",
            "ready_for_strategy": "build_strategy",
        },
    )
    graph.add_edge("plan_research", "normalize_research")
    graph.add_edge("normalize_research", "dispatch_queries")
    graph.add_edge("dispatch_queries", "plan_copywriting_query")
    graph.add_edge("dispatch_queries", "plan_product_query")
    graph.add_edge("plan_copywriting_query", "retrieve_copywriting")
    graph.add_edge("plan_product_query", "retrieve_product_docs")
    graph.add_edge("retrieve_copywriting", "build_company_understanding")
    graph.add_edge("retrieve_product_docs", "build_company_understanding")
    graph.add_edge("build_company_understanding", "build_strategy")
    graph.add_edge("build_strategy", "draft_email")
    graph.add_edge("draft_email", "review_grounding")
    graph.add_edge("draft_email", "review_copy")
    graph.add_edge("review_grounding", "join_reviews")
    graph.add_edge("review_copy", "join_reviews")
    graph.add_conditional_edges(
        "join_reviews",
        route_after_reviews,
        {
            "revise": "mark_revision",
            "final_reasoning": "final_reasoning",
        },
    )
    graph.add_edge("mark_revision", "draft_email")
    graph.add_edge("final_reasoning", END)
    return graph.compile()


def build_default_dependencies(
    *,
    copywriting_dir: str | Path,
    product_docs_dir: str | Path,
    required_roles: set[str] | None = None,
) -> FlowDependencies:
    required_roles = required_roles or set(ROLE_DEFAULTS) - {"EMBEDDINGS"}
    embeddings = _build_embeddings()
    copywriting_kb = build_knowledge_base(
        copywriting_dir,
        source_type="copywriting",
        embeddings=embeddings,
    )
    product_kb = build_knowledge_base(
        product_docs_dir,
        source_type="product_docs",
        embeddings=embeddings,
    )

    dependencies: FlowDependencies = {
        "copywriting_kb": copywriting_kb,
        "product_kb": product_kb,
    }
    role_builders = {
        "HITL_REVIEWER": ("hitl_reviewer_model", 0, True),
        "COMPANY_UNDERSTANDING": ("company_understanding_model", 0.1, True),
        "RESEARCH_PLANNER": ("research_planner_model", 0.1, True),
        "RESEARCH_NORMALIZER": ("research_normalizer_model", 0.1, True),
        "QUERY_PLANNER": (
            ("copywriting_query_planner_model", "product_query_planner_model"),
            0.1,
            True,
        ),
        "STRATEGIST": ("strategist_model", 0.2, True),
        "DRAFTER": ("drafter_model", 0.4, True),
        "GROUNDING_REVIEWER": ("grounding_reviewer_model", 0, True),
        "COPY_REVIEWER": ("copy_reviewer_model", 0, True),
        "FINAL_REASONER": ("final_reasoner_model", 0.2, False),
    }

    for role in required_roles:
        if role not in role_builders:
            raise ConfigurationError(
                code="unknown_required_role",
                message="Dependency builder received an unknown role.",
                context={"role": role},
            )
        key_name, temperature, structured_required = role_builders[role]
        model = _build_chat_model(
            role,
            temperature=temperature,
            structured_required=structured_required,
        )
        if isinstance(key_name, tuple):
            for item in key_name:
                dependencies[item] = model
        else:
            dependencies[key_name] = model
    return dependencies


def run_email_sdr_flow_with_dependencies(
    *,
    dependencies: FlowDependencies,
    product_docs_dir: str | Path,
    product_profile: ProductProfile,
    account_research: AccountResearch | None = None,
    raw_account_research: RawAccountResearch | None = None,
    product_docs_review: HumanReviewReport | None = None,
    hitl_only: bool = False,
    halt_on_hitl_findings: bool = False,
) -> FlowState:
    initial_state = _prepare_company_understanding_state(
        dependencies=dependencies,
        product_docs_dir=product_docs_dir,
        product_profile=product_profile,
        raw_account_research=raw_account_research,
        account_research=account_research,
        product_docs_review=product_docs_review,
    )

    if hitl_only or (
        halt_on_hitl_findings
        and _human_review_required(
            initial_state.get("product_docs_review"),
            initial_state.get("prospect_research_review"),
            initial_state.get("company_understanding_review"),
        )
    ):
        initial_state["halted_for_human_review"] = True
        log_event(
            "flow.halted_for_human_review",
            hitl_only=hitl_only,
            halt_on_hitl_findings=halt_on_hitl_findings,
        )
        return initial_state

    app = build_email_sdr_flow(dependencies)
    return app.invoke(initial_state)


def run_email_sdr_flow(
    *,
    product_profile: ProductProfile,
    account_research: AccountResearch | None = None,
    raw_account_research: RawAccountResearch | None = None,
    copywriting_dir: str | Path,
    product_docs_dir: str | Path,
    hitl_only: bool = False,
    halt_on_hitl_findings: bool = False,
) -> FlowState:
    dependencies = build_default_dependencies(
        copywriting_dir=copywriting_dir,
        product_docs_dir=product_docs_dir,
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
    return run_email_sdr_flow_with_dependencies(
        dependencies=dependencies,
        product_docs_dir=product_docs_dir,
        product_profile=product_profile,
        account_research=account_research,
        raw_account_research=raw_account_research,
        hitl_only=hitl_only,
        halt_on_hitl_findings=halt_on_hitl_findings,
    )
