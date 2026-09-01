# fn-ignis Operating Protocol for OpenAI Codex Agents 🤖

## Context & Architecture
`fn-ignis` operates on a Dual-Track Architecture:
- Track 1 (Always-On Radar): 24/7 autonomous surveillance across Google Trends, YouTube, and TikTok (`fn-ignis-worker`).
- Track 2 (Targeted Deep Probes): Interactive, hypothesis-driven market research missions.

## Session Continuity
When entering a conversation thread, extract the thread ID (e.g. `codex://threads/<thread_id>`) and call `get_current_session_mission(session_id)` to restore context.

## 6-Step Market Research SOP
1. **Clarify Objectives & Core Hypothesis**: Set target business model and falsifiable hypothesis. Call `register_domain_lexicon(domain, terms)` if the domain has niche slang or tool names.
2. **Macro Scan & Keywords**: Call `get_tiktok_creative_center_trends(geo, period, limit, industry)` and `get_tiktok_search_suggestions(keywords, geo)`.
3. **Deep Multi-Platform Ingress**: Call `create_research_mission` and `execute_mission_ingress`. Ensure Quality Scorecard confidence $\ge 70\%$.
4. **4-Lens Breakdown**: Evaluate Google Search, YouTube long-form, TikTok short-form, and Voice of Customer pain points via `extract_customer_pain_points`.
5. **Cross-Platform Synthesis**: Compute `Opportunity Index` (+100 to -100) and identify `HIGH_DEMAND_LOW_SUPPLY` gaps.
6. **Strategic Verdict & Actionable Plan**: Summarize market truths, evaluate entry risks, formulate a 3-7 day MVP validation plan, and export the interactive dashboard via `generate_mission_artifact`.
