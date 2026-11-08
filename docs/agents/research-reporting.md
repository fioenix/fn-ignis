# Strategic Research and Reporting

Read this before running a strategic Market research mission or rendering a dossier or HTML artifact.

## Strategic Market research

1. Frame the decision backwards from the outcome. Confirm a Mission Manifest, allowed sources,
   authority boundary, cost, output, stop conditions, and retention policy.
2. Confirm the Market Brief: target user, problem, hypothesis, at least two alternatives, null
   hypothesis, falsifiers, kill criteria, and revision rule.
3. Plan and run only authorized probes. Preserve every channel's measured outcome, including
   auth failure, rate limit, degradation, and healthy emptiness.
4. Qualify each observation against the current Brief and collection-plan frame, including
   support, contradiction, and context. Do not promote external files or earlier Attention
   observations to primary evidence without mission-scoped verification.
5. Submit typed candidate claims against the current evidence-frame digest. Read the current
   Claim Ledger. Render permitted claims with citations, contradiction, limitations, and decision
   conditions; otherwise render the Gap Report and next-best probe.
6. Stop at completion, insufficient evidence, cancellation, failure, or missing authority.

This is an analytical reference, not an unskippable pipeline for tactical calls. Outcome thinking
defines the decision, design thinking locates the user and method, and critical thinking actively
tests the initial belief.

## Campaign Identification Banner
When executing a formal Strategic Research Campaign, prefix the analysis with the campaign identifier banner:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

## Native Artifacts First
- Render source coverage, permitted claims, or a Gap Report directly in chat at the level of detail the user requested.
- Export standalone HTML files to `reports/` via `generate_mission_artifact` when the user requests a persistent local dossier.

## 🎨 FINOLABS Design System

Every HTML artifact renders in the FINOLABS design system. The tokens are vendored into
`src/ignis/infrastructure/templates/html/_fino_theme.html` from the "Finolabs Design System"
project on claude.ai/design (`theme.css`); update that partial when the source moves, and keep the
values byte-identical rather than eyeballing new ones.

Rules that apply to artifacts specifically:
- Artifacts are **product surfaces**: `<body class="product-mode">`, density and data-viz tokens,
  never the marketing register on the same page.
- **Type**: Anton for display caps, Space Grotesk for UI and body, JetBrains Mono for numbers and
  machine labels. Numbers use `font-variant-numeric: tabular-nums`.
- **Colour**: never hard-code hex. Chrome reads the role tokens (`--color-foreground`,
  `--color-border`), series read the data-viz slots (`--color-chart-1..12`), labels read the tag
  pairs. Mint is the everyday brand colour; violet is reserved for a single high-stakes accent.
- **No emoji.** `→ ↗ • — ◆ ◇` are the allowed glyphs; `→` is the canonical action glyph.
- **Radius** `--radius-lg` for cards, `--radius-full` for chips; shadows only `xs`, `md`, `xl`.
- Artifacts may fetch the FINOLABS webfonts, and nothing else external beyond the CDN libraries a
  template already declares. The trend graph renders its canvas and force layout inline so the
  export stays usable offline.

## 📊 Evidence Attribution Standards
When presenting strategic conclusions, agents must maintain evidentiary integrity:
1. **Data Ingress Summary Table**:
   - Explicitly list every requested channel, including those that did not run or could not be measured.
   - Display counts and exact channel state from the current evidence frame; never equate missingness with zero.
2. **Inline Evidence Citations**:
   - Render only current-frame `PERMITTED` Claim Ledger entries with their observation bindings.
   - Disclose contradiction, sample limitations, denominator/timeframe for measurements, and conditions that would change the decision.

## 🧾 Recommended Full Strategic Report Structure
When compiling a Comprehensive Strategic Dossier, the following standard structure is recommended:
1. **Campaign Identification Banner**
2. **Data Ingress Summary Table** (from `channel_summaries`)
3. **Quality Scorecard**
4. **Single-Source 4-Lens Breakdown** (with source citations)
5. **Current-frame Claim Ledger and counterevidence** (only permitted claims)
6. **Decision conditions or Gap Report** (never invent a verdict when evidence fails)

*(For ad-hoc queries, agents should adjust output format flexibly to match the user's specific conversational need).*
