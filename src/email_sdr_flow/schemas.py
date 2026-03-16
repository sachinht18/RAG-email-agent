from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _clean_string_list(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        cleaned_items: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text and text not in cleaned_items:
                cleaned_items.append(text)
        return cleaned_items
    return value


def _require_non_empty_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


class FrameworkModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class RawAccountResearch(FrameworkModel):
    prospect_id: str | None = None
    account_name: str
    account_domain: str | None = None
    target_persona_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_persona_name", "persona_name"),
    )
    target_persona_role: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_persona_role", "persona_role"),
    )
    raw_company_notes: list[str] = Field(default_factory=list)
    raw_person_notes: list[str] = Field(default_factory=list)
    raw_recent_signals: list[str] = Field(default_factory=list)
    raw_pain_hypotheses: list[str] = Field(default_factory=list)
    raw_stack_signals: list[str] = Field(default_factory=list)
    raw_source_urls: list[str] = Field(default_factory=list)
    desired_cta: str = "Open to a 15-minute conversation next week?"

    @field_validator("account_name", "desired_cta")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator(
        "raw_company_notes",
        "raw_person_notes",
        "raw_recent_signals",
        "raw_pain_hypotheses",
        "raw_stack_signals",
        "raw_source_urls",
        mode="before",
    )
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class ProductProfile(FrameworkModel):
    company_name: str
    product_name: str
    product_category: str | None = Field(
        default=None,
        validation_alias=AliasChoices("product_category", "category"),
    )
    one_line_summary: str = Field(
        validation_alias=AliasChoices("one_line_summary", "summary")
    )
    ideal_customer_profile: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ideal_customer_profile", "icp"),
    )
    core_problem: str | None = None
    key_capabilities: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    proof_points: list[str] = Field(default_factory=list)
    terminology_guardrails: list[str] = Field(default_factory=list)
    avoid_claims: list[str] = Field(default_factory=list)
    default_cta: str = "Open to a 15-minute conversation next week?"

    @field_validator("company_name", "product_name", "one_line_summary", "default_cta")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator(
        "key_capabilities",
        "differentiators",
        "proof_points",
        "terminology_guardrails",
        "avoid_claims",
        mode="before",
    )
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class AccountResearch(FrameworkModel):
    account_name: str
    account_domain: str | None = None
    industry: str | None = None
    persona_name: str = Field(
        validation_alias=AliasChoices("persona_name", "target_persona_name")
    )
    persona_role: str = Field(
        validation_alias=AliasChoices("persona_role", "target_persona_role")
    )
    company_summary: str
    strategic_initiatives: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("pain_points", "business_pains"),
    )
    recent_signals: list[str] = Field(default_factory=list)
    personalization_hooks: list[str] = Field(default_factory=list)
    known_stack: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("known_stack", "tech_stack", "raw_stack_signals"),
    )
    desired_cta: str = "Open to a 15-minute conversation next week?"

    @field_validator("account_name", "persona_name", "persona_role", "company_summary", "desired_cta")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator(
        "strategic_initiatives",
        "pain_points",
        "recent_signals",
        "personalization_hooks",
        "known_stack",
        mode="before",
    )
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class RetrievalPlan(FrameworkModel):
    query: str = Field(description="Search query for the target knowledge base.")
    intent: str = Field(
        description="Short explanation of what this retrieval step is trying to learn."
    )

    @field_validator("query", "intent")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)


class DraftStrategy(FrameworkModel):
    messaging_angle: str = Field(
        description="Single sentence describing the best wedge for this account."
    )
    personalization_angle: str = Field(
        description="Specific opener angle tied to the account research."
    )
    chosen_pain_point: str = Field(
        description="The single pain point this email should anchor on."
    )
    value_hypothesis: str = Field(
        description="How the product changes the buyer's workflow."
    )
    proof_to_use: str = Field(
        description="The best factual proof point from product docs."
    )
    cta_strategy: str = Field(
        description="How to frame the CTA with low friction."
    )

    @field_validator(
        "messaging_angle",
        "personalization_angle",
        "chosen_pain_point",
        "value_hypothesis",
        "proof_to_use",
        "cta_strategy",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)


class ResearchPlan(FrameworkModel):
    account_summary: str = Field(
        description="Short summary of what seems to matter about the account."
    )
    priority_research_angles: list[str] = Field(
        default_factory=list,
        description="Key dimensions the rest of the flow should care about.",
    )
    likely_business_pains: list[str] = Field(
        default_factory=list,
        description="Likely pains inferred from the raw research notes.",
    )
    personalization_opportunities: list[str] = Field(
        default_factory=list,
        description="Potential hooks worth using in outbound messaging.",
    )
    research_gaps: list[str] = Field(
        default_factory=list,
        description="Important missing details that would strengthen the email.",
    )

    @field_validator("account_summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _require_non_empty_text(value, "account_summary")

    @field_validator(
        "priority_research_angles",
        "likely_business_pains",
        "personalization_opportunities",
        "research_gaps",
        mode="before",
    )
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


ConfidenceLevel = Literal["high", "medium", "low"]
PortfolioShape = Literal[
    "single_product",
    "multi_product",
    "platform",
    "service_heavy",
    "hybrid",
    "unclear",
]
PortfolioComplexity = Literal["simple", "moderate", "complex", "unclear"]
BuyerType = Literal["technical", "business", "both", "unclear"]
GtmMotion = Literal[
    "self_serve",
    "sales_led",
    "plg",
    "enterprise_led",
    "service_led",
    "channel_led",
    "hybrid",
    "unclear",
]
ValueLever = Literal[
    "productivity",
    "cost",
    "risk",
    "quality",
    "speed",
    "conversion",
    "consistency",
    "enablement",
    "qualification_quality",
    "support_load_reduction",
    "operational_control",
    "user_experience",
    "other",
]
ValueFrame = Literal[
    "direct_roi",
    "operational_leverage",
    "user_experience_improvement",
    "mixed",
    "unclear",
]
SupportLevel = Literal["grounded", "partially_grounded", "speculative"]


class WorkflowLayeringOpportunity(FrameworkModel):
    workflow_step: str
    target_team: str
    current_motion: str
    product_role: str
    value_levers: list[ValueLever] = Field(default_factory=list)
    value_frame: ValueFrame = "unclear"
    support_level: SupportLevel = "speculative"
    reasoning: str

    @field_validator(
        "workflow_step",
        "target_team",
        "current_motion",
        "product_role",
        "reasoning",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator("value_levers", mode="before")
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class OutreachImplications(FrameworkModel):
    best_messaging_angle: str
    anchor_pain: str
    safe_proof_points: list[str] = Field(default_factory=list)
    avoid_in_copy: list[str] = Field(default_factory=list)
    cta_style: str
    angle_notes: list[str] = Field(default_factory=list)

    @field_validator("best_messaging_angle", "anchor_pain", "cta_style")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator("safe_proof_points", "avoid_in_copy", "angle_notes", mode="before")
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class ConfidenceBySection(FrameworkModel):
    company_shape: ConfidenceLevel = "low"
    way_of_working: ConfidenceLevel = "low"
    product_fit: ConfidenceLevel = "low"
    ambiguities_and_risks: ConfidenceLevel = "low"
    outreach_implications: ConfidenceLevel = "low"


class CompanyUnderstanding(FrameworkModel):
    company_summary: str
    business_model_hypothesis: str
    what_the_company_sells: str
    portfolio_shape: PortfolioShape = "unclear"
    portfolio_complexity: PortfolioComplexity = "unclear"
    buyer_type_hypothesis: BuyerType = "unclear"
    likely_gtm_motion: GtmMotion = "unclear"
    likely_buyer_journey: str
    likely_internal_teams: list[str] = Field(default_factory=list)
    likely_existing_workflow: str
    likely_systems_or_handoffs: list[str] = Field(default_factory=list)
    workflow_friction_points: list[str] = Field(default_factory=list)
    volume_or_coordination_problem: str
    product_layering_opportunities: list[WorkflowLayeringOpportunity] = Field(
        default_factory=list
    )
    value_levers: list[ValueLever] = Field(default_factory=list)
    strongest_team_wedge: str
    strongest_safe_wedge: str
    value_frame: ValueFrame = "unclear"
    grounded_facts: list[str] = Field(default_factory=list)
    workflow_hypotheses: list[str] = Field(default_factory=list)
    speculative_inferences: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    unsupported_assumptions: list[str] = Field(default_factory=list)
    overclaim_risks: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    outreach_implications: OutreachImplications
    confidence_by_section: ConfidenceBySection = Field(
        default_factory=ConfidenceBySection
    )

    @field_validator(
        "company_summary",
        "business_model_hypothesis",
        "what_the_company_sells",
        "likely_buyer_journey",
        "likely_existing_workflow",
        "volume_or_coordination_problem",
        "strongest_team_wedge",
        "strongest_safe_wedge",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator(
        "likely_internal_teams",
        "likely_systems_or_handoffs",
        "workflow_friction_points",
        "value_levers",
        "grounded_facts",
        "workflow_hypotheses",
        "speculative_inferences",
        "ambiguities",
        "contradictions",
        "unsupported_assumptions",
        "overclaim_risks",
        "clarification_questions",
        mode="before",
    )
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)

    @model_validator(mode="after")
    def validate_minimum_content(self) -> "CompanyUnderstanding":
        if not self.value_levers:
            raise ValueError("value_levers must include at least one value lever.")
        if not self.product_layering_opportunities:
            raise ValueError(
                "product_layering_opportunities must include at least one workflow opportunity."
            )
        return self


class HumanReviewItem(FrameworkModel):
    category: Literal[
        "ambiguity",
        "contradiction",
        "name_collision",
        "conflict",
        "clarification_needed",
    ]
    severity: Literal["low", "medium", "high"]
    title: str
    description: str
    affected_terms: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    question_for_human: str

    @field_validator("title", "description", "question_for_human")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)

    @field_validator("affected_terms", "source_refs", mode="before")
    @classmethod
    def clean_list_fields(cls, value: object) -> object:
        return _clean_string_list(value)


class HumanReviewReport(FrameworkModel):
    scope: Literal["prospect_research", "product_docs", "company_understanding"]
    summary: str
    requires_human_review: bool = Field(
        validation_alias=AliasChoices(
            "requires_human_review",
            "human_review_required",
            "needs_human_review",
        )
    )
    items: list[HumanReviewItem] = Field(default_factory=list)

    @field_validator("requires_human_review", mode="before")
    @classmethod
    def normalize_requires_human_review(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "required", "needs_review"}:
                return True
            if lowered in {"false", "no", "not_required"}:
                return False
        return value

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _require_non_empty_text(value, "summary")

    @model_validator(mode="after")
    def validate_items(self) -> "HumanReviewReport":
        if self.requires_human_review and not self.items:
            raise ValueError(
                "items must include at least one actionable finding when human review is required."
            )
        return self


class HumanReviewAction(FrameworkModel):
    decision: Literal["pending", "approve", "reject", "clarify"] = "pending"
    message: str = ""
    decided_at: str | None = None

    @model_validator(mode="after")
    def validate_message_requirements(self) -> "HumanReviewAction":
        if self.decision == "clarify" and not self.message.strip():
            raise ValueError("clarify decisions require a non-empty message.")
        return self


class ReviewCheckpoint(FrameworkModel):
    report: HumanReviewReport
    action: HumanReviewAction = Field(default_factory=HumanReviewAction)


class WorkflowSession(FrameworkModel):
    schema_version: int = 1
    session_id: str
    created_at: str
    updated_at: str
    status: Literal[
        "pending_review",
        "ready_to_resume",
        "rejected",
        "completed",
    ]
    copywriting_dir: str
    product_docs_dir: str
    product_profile: ProductProfile | None = None
    raw_account_research: RawAccountResearch | None = None
    account_research: AccountResearch | None = None
    research_plan: ResearchPlan | None = None
    copywriting_query: str | None = None
    product_query: str | None = None
    copywriting_retrieval_diagnostics: dict[str, Any] = Field(default_factory=dict)
    product_retrieval_diagnostics: dict[str, Any] = Field(default_factory=dict)
    copywriting_snippets: list["GroundingSnippet"] = Field(default_factory=list)
    product_snippets: list["GroundingSnippet"] = Field(default_factory=list)
    company_understanding: CompanyUnderstanding | None = None
    prospect_research_review: ReviewCheckpoint
    product_docs_review: ReviewCheckpoint
    company_understanding_review: ReviewCheckpoint | None = None
    result_snapshot: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_consistency(self) -> "WorkflowSession":
        if self.schema_version != 1:
            raise ValueError("Unsupported workflow session schema version.")
        if self.company_understanding is not None and self.company_understanding_review is None:
            raise ValueError(
                "company_understanding_review is required when company_understanding is present."
            )
        if self.status != "completed":
            decisions = [
                self.prospect_research_review.action.decision,
                self.product_docs_review.action.decision,
            ]
            if self.company_understanding_review is not None:
                decisions.append(self.company_understanding_review.action.decision)
            derived_status = (
                "rejected"
                if any(decision == "reject" for decision in decisions)
                else "ready_to_resume"
                if all(decision in {"approve", "clarify"} for decision in decisions)
                else "pending_review"
            )
            if self.status != derived_status:
                raise ValueError(
                    f"session status {self.status!r} is inconsistent with review decisions."
                )
        return self


class GroundingSnippet(FrameworkModel):
    source_type: Literal["copywriting", "product_docs"]
    title: str
    source_path: str
    excerpt: str

    @field_validator("title", "source_path", "excerpt")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)


class EmailDraft(FrameworkModel):
    subject_lines: list[str] = Field(
        min_length=2,
        max_length=3,
        description="Two or three concise subject line options.",
    )
    personalization_angle: str
    opener: str
    pain_reframe: str
    value_prop: str
    proof: str
    call_to_action: str
    email_body: str = Field(
        description="Final email body using 4 to 6 short sentences."
    )
    citations: list[GroundingSnippet] = Field(default_factory=list)

    @field_validator(
        "subject_lines",
        mode="before",
    )
    @classmethod
    def normalize_subject_lines(cls, value: object) -> object:
        return _clean_string_list(value)

    @field_validator(
        "personalization_angle",
        "opener",
        "pain_reframe",
        "value_prop",
        "proof",
        "call_to_action",
        "email_body",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, info.field_name)


class ReviewResult(FrameworkModel):
    approved: bool = Field(
        validation_alias=AliasChoices("approved", "approval_status", "approval")
    )
    issues: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("issues", "rejection_reasons", "rejection_reason"),
    )
    rewrite_brief: str = ""

    @field_validator("approved", mode="before")
    @classmethod
    def normalize_approved(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"approve", "approved", "true", "yes"}:
                return True
            if lowered in {"reject", "rejected", "false", "no"}:
                return False
        return value

    @field_validator("issues", mode="before")
    @classmethod
    def normalize_issues(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def validate_rejected_content(self) -> "ReviewResult":
        if not self.approved and not self.issues:
            self.issues = ["Reviewer rejected the draft but did not provide specific issues."]
        if not self.approved and not self.rewrite_brief.strip():
            self.rewrite_brief = (
                "Tighten the draft to remove unsupported claims and make the critique actionable."
            )
        return self
