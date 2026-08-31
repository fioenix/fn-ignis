---
name: fn-ignis-harness
description: Autonomous Trend Intelligence & Market Opportunity Agent Harness for deep multi-platform listening, white-space analysis, human-friendly mission tracking, and cross-agent session mapping.
---

# fn-ignis Trend Intelligence & Market Opportunity Agent Harness 🚀

This skill equips AI agents with an autonomous trend intelligence harness:
1. **Cross-Agent Session Tracing**: Binds `agent` (`claude_desktop`, `claude_code`, `codex`) and `session_id` (`codex://threads/...`, `conversation_id`) to missions. Automatically restores research context across chat restarts.
2. **Human-Friendly Mission Tracking (Shortcode UX)**: Assigns clean, human-readable identifiers (`FB16C5EE` or `VN-AI-AGENT-90D`).
3. **Quality & Integrity Scorecard**: Multi-dimensional confidence evaluation (Coverage, Language Precision, Freshness, Creator Diversity).
4. **White Space Discovery**: Identifies high-demand, low-supply market gaps by correlating search intent (Google Trends) with verified localized supply (YouTube/TikTok).
5. **Claude Native Artifacts First**: Emphasizes direct in-chat visual rendering.

---

## 🎨 Mandatory Presentation Guidelines

### 1. Research Campaign Identification Banner
When reporting mission status or analysis, **ALWAYS display the identification banner**:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

### 2. Artifact Presentation Protocol (Native Artifacts First) 🌟
- **DEFAULT IN-CHAT PRESENTATION:** When the user requests a mission report or analysis, call `get_mission_analysis(mission_id)` and **render the findings directly as a Claude Native Artifact** in the chat window.
  - Use high-contrast Light Mode styling, visual summary cards, and structured tables.
  - Follow the 5-act storyflow: *Executive Pulse $\rightarrow$ Scorecard Radar $\rightarrow$ White Space Matrix (10 topics) $\rightarrow$ Strategic Insights & Action Blueprint $\rightarrow$ Supporting Signal Evidence*.
- **LOCAL FILE EXPORT:** Call `generate_mission_artifact` ONLY when the user explicitly asks to export or save a standalone HTML report file to local disk (`reports/` folder).

---

## 🛠️ FastMCP Tool Reference

### 1. `get_current_session_mission(session_id="...")`
- Automatically retrieves and resumes the active mission linked to the current chat session.

### 2. `execute_mission_ingress(mission_id="...")`
- Executes deep multi-platform ingestion (idempotent replace mode, strict date filters, and noise rejection).

### 3. `get_mission_analysis(mission_id="...")` *(RECOMMENDED FOR CHAT ARTIFACTS)*
- Fetches the complete strategic analysis payload (Scorecard, 10 White Spaces, Insights, Action Plan, Top Signals) in a lightweight JSON payload (~3KB).

### 4. `generate_mission_artifact(mission_id="...")` *(EXPLICIT FILE EXPORT ONLY)*
- Renders and writes a standalone single-file HTML Infographic Canvas report to `reports/`.
