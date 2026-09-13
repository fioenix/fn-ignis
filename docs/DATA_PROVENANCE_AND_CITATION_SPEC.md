# 📑 PRD & ARCHITECTURAL SPECIFICATION
## Epic 2: Data Provenance, Ingress Health Audit & Citation Attribution Engine

- **Epic Code:** `EPIC-PROVENANCE-01`
- **Objective:** Eliminate vague assertions and hallucinations in AI Agent market intelligence reports; provide granular Data Provenance audits and Channel Health Observability across all ingress pipelines.
- **Status:** `PARTIALLY IMPLEMENTED` — platform-level health and strategic-insight citations are
  live; exact observation references and two report consumers remain open
- **Author:** Antigravity (Product Manager)
- **Implementer:** Claude Code & Antigravity (Pair Programming)

---

## 🎯 1. Background & Problem Statement

During market research campaigns, multi-source AI agents previously faced two critical reliability risks:

1. **Missing Evidence Citations**:
   - Strategic takeaways were often generalized without direct references to originating content (e.g., *"Users report high pricing and difficult integration"*, *"Opportunity score: 85"*).
   - Stakeholders and analysts could not determine whether conclusions were derived from real customer comments or LLM speculation.
2. **Silent Ingress Failures**:
   - When a specific channel failed silently (e.g., expired tokens on Threads, CAPTCHA block on TikTok, YouTube quota exhaustion), the system continued generating reports based on residual data without warning users that key data sources were empty.

---

## 🏛️ 2. Architectural Solution

To guarantee evidentiary integrity, the system implements:

### A. Channel Health Audit (`ChannelSummary`)
Every mission analysis produces the status of each data pipeline:
- `HEALTHY`: Successfully retrieved signals meeting expected thresholds.
- `EMPTY_NO_DATA`: Channel completed without errors but zero relevant signals were found.
- `AUTH_REQUIRED`: Credential or session expired; requires user re-authentication.
- `RATE_LIMITED`: Platform temporary rate limit encountered; backoff active.
- `DEGRADED`: Partial recovery or fallback mode engaged.

### B. In-Line Citation Attribution (`CitationPill`)
All extracted customer pain points, trend summaries, and strategic findings must retain source provenance:
- Exact `observation_id`, which MUST belong to the report mission through `mission_evidence`.
- Origin platform (`YouTube`, `TikTok`, `Threads`, `Google Trends`).
- Concrete artifact attribution (video title, view count, post timestamp, creator handle).
- Verifiable numeric evidence (e.g., *"35/84 comments on @creator video cited complex setup"*).

The citation identity is the observation identifier. URL and title are display payload, not a
second identity key. Implementations MUST NOT deduplicate citations with
`platform + source_url/title`; the canonical source resolver and mission evidence ledger already
own that decision.

### Current implementation boundary (verified 2026-09-13)

- Implemented: five platform-level `ChannelDataSummary` rows, all five health statuses, a top
  citation per healthy platform, typed citations on `StrategicInsight`, HTML audit table and
  strategic-insight citation pills, and FastMCP serialization of those fields.
- Not implemented: separate health for TikTok Video Grid versus TikTok Comments. Both currently
  collapse into `PlatformType.TIKTOK`, so one healthy surface can hide another failing surface.
- Not implemented: typed citations on `MarketOpportunity` and `ActionableTakeaway`; those models
  still carry strings.
- Not implemented: `CitationEvidence.observation_id`. The current citation registry keys on
  platform plus URL-or-title, which can disagree with canonical source identity and cannot prove
  which mission observation supported a claim.

### C. Multi-Layer Defense-in-Depth PII Sanitization
User identifiers, phone numbers, email addresses, and auth tokens are scrubbed:
1. **Ingress Layer**: Sanitized immediately upon connector capture.
2. **Persistence Layer**: Stored only in sanitized form.
3. **Presentation Layer**: HTML templates and markdown renderers apply secondary filters (`|sanitize_pii`) to guarantee zero accidental leakage.

---

## 🛡️ 3. Verification & Compliance Checklist

- [x] All 5 target platforms report structured health states.
- [ ] Connector-surface health distinguishes TikTok Video Grid from TikTok Comments.
- [x] HTML artifacts embed interactive source pills for strategic insights.
- [ ] Market opportunities and actionable takeaways carry typed citations.
- [ ] Every citation references an observation present in the mission evidence ledger.
- [x] PII sanitization test suite passes 100% across all ingress and templating paths.
- [x] FastMCP tool `evaluate_mission_quality` computes composite health and diversity metrics.
