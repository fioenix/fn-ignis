# fnIgnis 🔥 — Meta Integration Guide (Threads & Instagram Reels)
## Dual-UX Architecture: 1-Click Zero-Setup for Non-Tech & Deep Graph API for Power Users

This document defines the integration architecture, step-by-step instructions, and **Agent-Operable Runbooks** for connecting Meta platforms: **Threads** and **Instagram Reels**.

---

## 📑 Table of Contents
1. [Dual-UX Model: Selecting Your Integration Tier](#1-dual-ux-model-selecting-your-integration-tier)
2. [Tier 1: 1-Click Experience for Non-Tech Users (Zero-Setup Onboarding)](#2-tier-1-1-click-experience-for-non-tech-users-zero-setup-onboarding)
   - [How It Works](#how-tier-1-works)
   - [Data Yield & Trade-offs](#data-yield--trade-offs)
3. [Tier 2: Deep Meta Graph API for Power Users & Enterprise](#3-tier-2-deep-meta-graph-api-for-power-users--enterprise)
   - [Step 1: Register Application on Meta Developer Portal](#step-1-register-application-on-meta-developer-portal)
   - [Step 2: Configure Scopes & Redirect URIs](#step-2-configure-scopes--redirect-uris)
   - [Step 3: Add Credentials to .env](#step-3-add-credentials-to-env)
   - [Step 4: Execute OAuth 2.0 Flow via FastMCP Tools](#step-4-execute-oauth-20-flow-via-fastmcp-tools)
4. [🤖 Agent Automation Runbook](#4--agent-automation-runbook)
5. [Credential Security Architecture & Token Lifecycle](#5-credential-security-architecture--token-lifecycle)
6. [Troubleshooting & FAQ](#6-troubleshooting--faq)

---

## 1. Dual-UX Model: Selecting Your Integration Tier

`fn-ignis` solves the friction of developer account setup through a two-tier approach:

| Capability | Tier 1: Zero-Setup Ingress (Default) | Tier 2: Deep Graph API (Enterprise) |
|---|---|---|
| **Target Audience** | Marketers, Indie Founders, Casual Analysts | Tech Leads, Data Engineers, Enterprise Ops |
| **Setup Time** | 0 minutes (instant) | 15–30 minutes (app registration required) |
| **Meta App Required** | No | Yes (Threads API & Instagram Basic Display) |
| **Data Yield** | Public trending topics, search autocomplete, top public posts | Full user profiles, engagement metrics, private media |
| **Reliability** | Public endpoints with defensive rate limiting | Official SLAs and higher rate limits |

---

## 2. Tier 1: 1-Click Experience for Non-Tech Users (Zero-Setup Onboarding)

### How Tier 1 Works
When no API keys are provided in `.env`, `fn-ignis` automatically falls back to:
- Direct GraphQL public queries for trending threads and keyword expansion.
- Public search suggestions for slang and user phrasing.
- PII-sanitized public snippet ingestion.

### Data Yield & Trade-offs
- **Yield**: Immediate signal ingestion without entering credentials or configuring OAuth.
- **Trade-off**: Lower rate limit ceilings compared to authenticated API quotas.

---

## 3. Tier 2: Deep Meta Graph API for Power Users & Enterprise

### Step 1: Register Application on Meta Developer Portal
1. Navigate to [Meta for Developers](https://developers.facebook.com/).
2. Click **My Apps** $ightarrow$ **Create App**.
3. Select **Other** $ightarrow$ **Business** (or Consumer).
4. Add the **Threads** product and/or **Instagram** product to your app.

### Step 2: Configure Scopes & Redirect URIs
Ensure the following OAuth scopes are requested:
- Threads: `threads_basic`, `threads_content_publish`, `threads_read_replies`
- Instagram: `instagram_basic`, `instagram_manage_insights`

Set the Valid OAuth Redirect URI to:
```
http://localhost:8080/auth/callback
```

### Step 3: Add Credentials to .env
Add the App ID and App Secret to your `.env`:
```ini
THREADS_APP_ID=your_threads_app_id
THREADS_APP_SECRET=your_threads_app_secret
INSTAGRAM_APP_ID=your_instagram_app_id
INSTAGRAM_APP_SECRET=your_instagram_app_secret
```

### Step 4: Execute OAuth 2.0 Flow via FastMCP Tools
Use the built-in MCP authentication tools:
```json
{
  "tool": "authenticate_threads",
  "arguments": {
    "code": "AQB..."
  }
}
```

---

## 4. 🤖 Agent Automation Runbook

When an AI Agent is tasked with connecting Meta channels, it follows this sequence:

1. **Check Status**:
   Call `get_threads_auth_status()` and `get_instagram_auth_status()`.
2. **Handle Unauthenticated State**:
   - If user provided API keys, guide or assist with OAuth exchange.
   - If no keys are provided, inform user and proceed with Tier 1 public listening automatically.
3. **Verify Health**:
   Call `verify_connectors_health()` to ensure connectors report `HEALTHY` or `DEGRADED_FALLBACK`.

---

## 5. Credential Security Architecture & Token Lifecycle

- **Encryption at Rest**: Tokens and secrets are encrypted with AES-256 Fernet using `ENCRYPTION_KEY`.
- **In-Memory Sanitization**: Plaintext credentials are never logged or exposed in LLM prompt contexts.
- **PII Scrubbing**: All inbound social payloads are stripped of phone numbers, emails, and auth tokens before ingestion.

---

## 6. Troubleshooting & FAQ

### Q: Why did Threads return fewer signals than expected?
A: Public endpoints may apply temporary rate limits if hit too rapidly. If deep ingestion is required, upgrade to Tier 2 with official Meta API keys.

### Q: How do I wipe saved credentials?
A: Call `clear_threads_auth()` or `clear_instagram_auth()`.
