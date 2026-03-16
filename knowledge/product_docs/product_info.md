# Docket.io Marketing Agent — Product Requirements Document (PRD)

**Document Type:** Product Requirements Document  
**Product:** Docket AI Marketing Agent  
**Version:** 1.0  
**Status:** Based on publicly documented production capabilities (March 2026)  
**Audience:** Product Managers, Engineering, GTM, Customer Success

***

## 1. Executive Summary

The Docket AI Marketing Agent is a purpose-built, B2B inbound conversion agent that transforms anonymous website traffic into qualified pipeline through real-time, knowledge-grounded conversation. It replaces static forms and legacy chatbots as the primary inbound engagement layer, operating 24/7 without human SDR involvement.[1]

The core product thesis: B2B buyers are 70% through their buying journey before contacting sales. They arrive on websites with specific evaluation questions — integration fit, security posture, pricing logic, use-case viability — that static pages cannot answer. The Marketing Agent closes this gap by acting as a digital SDR + SE: answering from verified knowledge, qualifying intent through structured discovery, and routing to the right human when the moment is right.[2][3][4]

**Core Output:** The Agent Qualified Lead (AQL) — a prospect that has engaged in a real discovery conversation, demonstrated genuine intent, and arrived with full context logged to CRM.[5]

***

## 2. Problem Statement

### 2.1 Business Problem

B2B marketing teams generate significant inbound traffic but convert poorly:

- Median B2B form conversion rate: 1.7%[3]
- 92–98% of website visitors leave without converting — even high-intent ones[3]
- Average lead response time: 42 hours; 30% of inbound leads are never contacted[3]
- Legacy chatbots (decision-tree based) break on off-script questions; buyers compare their experience to ChatGPT or Claude, not to 2016-era chatbots[3]
- MQLs are poor signal: they are behavioral proxies (page views, email opens) not evidence of genuine buying intent[5]

### 2.2 User Problem (Buyer Perspective)

Buyers at evaluation stage need answers to questions that cannot be answered by forms or static pages:

- Integration architecture and compatibility with their stack
- Security certifications and data handling policies
- Pricing logic and packaging fit for their company size
- Use-case validation and proof points from similar companies

When they can't get answers, they don't wait — they shortlist a competitor who got there first.[3]

### 2.3 User Problem (Marketing/GTM Team Perspective)

- Marketing teams cannot attribute pipeline to inbound traffic with precision
- SDR capacity is consumed by unqualified form submissions
- SE capacity is burned on early-stage technical questions that should never reach a human SE
- No first-party intent data is captured during website evaluation — only a name and email at the end

***

## 3. Goals and Success Metrics

### 3.1 Business Goals

| Goal | Target Metric |
|---|---|
| Increase qualified pipeline from existing traffic | +15% qualified pipeline average[2] |
| Improve win rate for AQL-sourced deals | +12% win rate average[1] |
| Reduce sales cycle length | -10% cycle length average[1] |
| Reduce customer acquisition cost | -6% CAC average[2] |
| Increase website engagement | +11% engagement rate[2] |
| Increase meeting volume | +30% booked meetings[1] |
| Time to deployment | 7–14 days from contract to live agent[1] |

### 3.2 Product Quality Metrics

| Metric | Target |
|---|---|
| Answer accuracy | 95%+ [6] |
| Hallucination rate | Sub-2.7%[6] |
| Response latency | Under 3 seconds (under 1 second for most queries)[7] |
| Language support | 40+ languages[8] |
| Human intervention rate | 0% for standard product, pricing, integration, compliance questions (agent handles 70–80%)[3] |

***

## 4. User Stories

### 4.1 Website Visitor (Buyer)

- As a **late-stage B2B buyer**, I want to get accurate answers to my evaluation questions (integration fit, pricing, security) immediately and at any hour, so that I can shortlist or disqualify a vendor without waiting 1–2 days for a sales rep
- As a **technical evaluator (CTO/VP Engineering)**, I want detailed answers about API architecture, data residency, SSO support, and compliance certifications, so that I can complete my security evaluation without scheduling a call
- As a **returning visitor**, I want the agent to remember my previous questions and context, so that I don't have to re-explain my situation on subsequent visits
- As a **buyer ready to book**, I want to schedule a meeting with the right sales rep immediately, without going through a form that adds 24+ hours of delay

### 4.2 Marketing Team (Agent Operator)

- As a **CMO**, I want measurable attribution between inbound traffic and qualified pipeline, so that I can defend my inbound spend to the CFO with conversation-level evidence
- As a **Demand Gen Manager**, I want the agent deployed on campaign landing pages so that paid traffic converts at rates higher than 1.7%
- As a **Marketing Ops Manager**, I want the agent to write full conversation context back to Salesforce/HubSpot automatically, so that AQLs arrive with qualification data attached and SDR triage time is eliminated

### 4.3 Sales Team (AQL Recipient)

- As an **Account Executive**, I want to receive booked meetings with a full conversation transcript, identified pain points, and qualification answers already logged, so that I can open discovery calls informed rather than exploratory
- As an **SDR**, I want real-time Slack alerts when a high-intent visitor requests a human handoff, so that I can take over warm conversations during business hours without lead leakage
- As a **Revenue Ops Manager**, I want routing rules that respect CRM ownership hierarchy (Opportunity → Account → Lead owner) before applying territory logic, so that no meetings land with the wrong rep

***

## 5. Core Functional Requirements

### 5.1 Conversation Engine

| Requirement | Description | Priority |
|---|---|---|
| FR-001 | Agent must answer questions from approved knowledge sources only; never generate answers from general LLM training data | P0 |
| FR-002 | Agent must support Voice Mode (speech-to-speech) and Text Mode (chat) selectable per deployment | P0 |
| FR-003 | Agent must respond in under 3 seconds for 95%+ of queries | P0 |
| FR-004 | Agent must weave BANT and MEDDIC discovery questions contextually during conversation — not as a form gate | P0 |
| FR-005 | Agent must support multimodal content delivery: slides (PPT/PPTX), videos, and PDFs surfaced mid-conversation | P1 |
| FR-006 | Agent must maintain short-term and long-term visitor memory; returning visitors resume in-context | P1 |
| FR-007 | Agent must support 40+ languages with automatic detection based on browser/region settings | P1 |
| FR-008 | Agent must escalate cleanly to a human (with full context) when a question is outside its knowledge base — never guess or hallucinate | P0 |
| FR-009 | Agent must capture and log: pages visited, questions asked, time on site, repeat visit count, expressed pain points, budget signals, timeline, and decision authority | P0 |

### 5.2 Knowledge Layer (Sales Knowledge Lake™)

| Requirement | Description | Priority |
|---|---|---|
| FR-010 | Platform must ingest 100+ data sources: CRM, call recordings (Gong), Slack, Google Drive, SharePoint, Notion, Confluence, product docs | P0 |
| FR-011 | Knowledge graph must resolve conflicts between sources (default to most recent, authoritative version) | P0 |
| FR-012 | Platform must recrawl customer website nightly for knowledge freshness | P0 |
| FR-013 | All knowledge must be versioned and admin-reviewable; sensitive topics (pricing, security, compliance) must have configurable guardrails | P0 |
| FR-014 | Answer accuracy must target 95%+ with hallucination rate below 2.7% | P0 |
| FR-015 | Agent must never use customer data to train shared models; each instance must be fully isolated | P0 |

### 5.3 Lead Qualification and Routing

| Requirement | Description | Priority |
|---|---|---|
| FR-016 | Routing must first query CRM for existing ownership: Opportunity Owner → Account Owner → Lead Owner (configurable priority order) | P0 |
| FR-017 | Agentic routing fallback must analyze live conversation signals + visitor enrichment data (company, size, industry, location) against plain-English routing rules configured by ops team | P0 |
| FR-018 | When multiple reps are eligible, round-robin selection must be applied across the eligible pool | P1 |
| FR-019 | Every AQL must include: conversation transcript, pain points, qualification score, objections raised, pages visited, and enrichment data | P0 |
| FR-020 | Agent must support BANT and MEDDIC qualification frameworks, configurable per deployment | P0 |

### 5.4 Meeting Booking

| Requirement | Description | Priority |
|---|---|---|
| FR-021 | Agent must integrate with Calendly, Chili Piper, HubSpot Meetings, and RevenueHero for direct in-conversation booking | P0 |
| FR-022 | Meeting booking CTA text must be configurable by admin | P1 |
| FR-023 | Agent must respect team availability, territory routing, and lead scores when triggering meeting booking | P0 |
| FR-024 | Calendar invites must be sent automatically upon meeting creation | P0 |

### 5.5 CRM Integration

| Requirement | Description | Priority |
|---|---|---|
| FR-025 | Salesforce integration must read CRM ownership records for routing and write conversation transcript, qualification fields, and meeting objects after booking[9] | P0 |
| FR-026 | HubSpot integration must create/update Contacts, Timeline Events, and Meeting objects; must support field mapping (read/write toggles per object)[10] | P0 |
| FR-027 | CRM sync must be automatic — no manual export or import required | P0 |

### 5.6 Agent Configuration

| Requirement | Description | Priority |
|---|---|---|
| FR-028 | Admins must be able to toggle Marketing Agent on/off independently of JavaScript snippet presence | P0 |
| FR-029 | Agent must support page-level targeting: all pages, selected pages, or button-click-only trigger | P0 |
| FR-030 | Widget appearance (colors, button text) must be customizable to match brand identity | P1 |
| FR-031 | Agent behavior (qualification logic, tone, escalation triggers) must be configurable via a plain-text Prompt field | P0 |
| FR-032 | Domain whitelisting must be configurable; agent must not activate on non-whitelisted domains | P0 |
| FR-033 | Work hours must be configurable per day with multiple time slots; timezone-aware | P1 |
| FR-034 | Post-work-hours-only mode must be available (widget only appears when team is offline) | P1 |
| FR-035 | Callout timing and triggers must be configurable for page-level deployments | P1 |

### 5.7 Agent-to-Human Handoff

| Requirement | Description | Priority |
|---|---|---|
| FR-036 | Handoff must be configurable via a plain-English Handoff Prompt describing escalation conditions | P0 |
| FR-037 | Slack channel notification must fire when handoff is triggered, including full conversation context | P0 |
| FR-038 | Handoff must only fire during configured Work Hours; if outside hours, agent continues without escalation | P0 |

### 5.8 Security and Access Control

| Requirement | Description | Priority |
|---|---|---|
| FR-039 | IP and ASN blocking must be configurable from the Marketing Agent settings panel | P1 |
| FR-040 | All data must be encrypted in transit (TLS 1.1+) and at rest | P0 |
| FR-041 | Complete audit trails must be maintained for every conversation | P0 |
| FR-042 | Role-based access controls must restrict configuration access by user role | P0 |
| FR-043 | Customer data must never be used to train shared models or be accessible across customer instances | P0 |
| FR-044 | Platform must maintain SOC 2 Type II, ISO 27001, and GDPR compliance continuously | P0 |

***

## 6. Non-Functional Requirements

| NFR | Description | Target |
|---|---|---|
| **Availability** | Marketing Agent must be available 24/7/365 | 99.9% uptime SLA |
| **Latency** | Response time for conversation queries | <3s (p95); <1s (p50) |
| **Scalability** | Concurrent conversation support | Unlimited (per Docket positioning)[1] |
| **Deployment speed** | Time from contract to first live conversation | 4–14 days[1][11] |
| **Onboarding effort** | Customer technical lift required | Zero coding; ~5 hours setup[7] |
| **Accuracy** | Answer accuracy from approved knowledge | 95%+[6] |
| **Hallucination rate** | Incorrect or fabricated answers | <2.7%[6] |
| **Language support** | Automatic multilingual handling | 40+ languages[8] |

***

## 7. Integration Requirements

### 7.1 Required Integrations (P0)

| Integration | Purpose |
|---|---|
| Salesforce | CRM routing + AQL write-back[8] |
| HubSpot | CRM routing + contact/meeting creation[10] |
| Calendly / Chili Piper / RevenueHero / HubSpot Meetings | In-conversation meeting booking[7] |
| Slack | Agent-to-Human Handoff alerts[4] |

### 7.2 Recommended Integrations (P1)

| Integration | Purpose |
|---|---|
| Google Drive / SharePoint | Knowledge source ingestion[12] |
| Gong | Call intelligence as knowledge input[8] |
| Demandbase / Clearbit | Account identification for ABM + routing[7] |
| Marketo | Marketing automation downstream of AQL[8] |
| Confluence / Notion | Product and internal knowledge ingestion[12] |

***

## 8. Out of Scope

The following capabilities are explicitly outside the Marketing Agent product boundary:

- Outbound prospecting or cold outreach initiation (this is an inbound-only product)
- Email marketing automation or nurture sequencing (Marketo/HubSpot handle downstream)
- Full marketing attribution platform (Docket captures conversation-level attribution; multi-touch attribution modeling is handled by integrated MAPs)
- EU-specific data residency hosting (not available as of early 2026)[7]
- Free trial or self-serve onboarding (white-glove onboarding is standard)[1]

***

## 9. Constraints and Dependencies

| Constraint | Detail |
|---|---|
| **SKU dependency** | Marketing Agent is an opt-in SKU; not included in all Docket plans by default[4] |
| **CRM requirement** | Optimal routing and AQL sync require a connected Salesforce or HubSpot instance |
| **Knowledge source quality** | Agent accuracy is bounded by the quality and completeness of ingested knowledge sources |
| **Handoff dependency** | Agent-to-Human Handoff requires Work Hours to be enabled; will not fire if Work Hours are off[4] |
| **Pricing floor** | Plans start at $36,000/year; all-inclusive but no SMB self-serve tier[1] |
| **OpenAI dependency** | Platform uses a combination of internal models and OpenAI for service delivery[13] |

***

## 10. Acceptance Criteria

The Marketing Agent is considered production-ready for a given customer deployment when:

1. **Knowledge coverage**: Agent answers 70%+ of submitted test questions from approved knowledge without human review
2. **CRM sync**: Booked meetings and conversation transcripts appear in CRM within 60 seconds of conversation completion
3. **Routing accuracy**: 100% of leads with existing CRM ownership route to the correct owner on first attempt
4. **Hallucination check**: Agent escalates (rather than answering) on 3 out of 3 test questions that fall outside the knowledge base
5. **Meeting booking**: End-to-end booking (conversation → calendar invite) completes in under 2 minutes
6. **Handoff**: Slack alert fires within 30 seconds of handoff trigger during configured Work Hours
7. **Multilingual**: Agent switches language correctly in response to a non-English opening question
8. **Domain restriction**: Agent does not render on a non-whitelisted domain even when the JavaScript snippet is present