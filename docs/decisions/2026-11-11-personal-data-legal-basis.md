# Decision: Record the Personal Data Legal Basis for Ignis Under Vietnam's 2026 Law

**Status:** Proposed (drafted by an agent on 2026-11-11; the owner sets the status after an outside legal read)
**Date:** 2026-11-11
**Scope:** The legal basis, retention and publication duties for what Ignis processes from public social content

## Context

Ignis processes public social content collected for one user's own research: comment and caption
text, per-mission author markers, accounts a requester declares for one mission, and publication
dates and counters. Principle VII already keeps author identity out of storage, tool output and
reports. The repository records no legal basis for the processing that remains.

Vietnam's Law on Personal Data Protection No. 91/2025/QH15 took effect on 2026-01-01, with Decree
356/2025/NĐ-CP of 2025-12-31 detailing it and replacing Decree 13/2023/NĐ-CP. Sources read on
2026-11-11 by an agent, not by a lawyer:

- LuatVietnam summary of Decree 356/2025/NĐ-CP: https://luatvietnam.vn/dan-su/nghi-dinh-356-2025-nd-cp-quy-dinh-chi-tiet-luat-bao-ve-du-lieu-ca-nhan-422896-d1.html
- PwC Vietnam legal brief, 2026-01-28: https://www.pwc.com/vn/vn/publications/legal-news-brief/20260128-new-rules-personal-data-protection.html
- Global Vietnam Lawyers alert on Law 91/2025/QH15: https://gvlawyers.com.vn/wp-content/uploads/2025/09/VN_Legal-alert-_Law-on-PDP-2025.pdf

Article numbers below follow the GV Lawyers alert and are **unverified** against the gazetted text.

## Gaps found in the repository (verified 2026-11-11)

1. Retention of 13 months is a label only. `src/ignis/application/use_cases/watchlists.py:32` says runs are
   "removable after 13 months by an explicit retention action", and Spec 016 FR-014 requires that action;
   no code deletes expired observations.
2. The 2026-10-21 decision requires consent before an artifact is published outside the machine; no
   check enforces it, and Spec 015 strips identity fields but not personal data inside free text.
3. No document maps Ignis's processing to a purpose, a legal basis and a deletion trigger.

## Proposed decision

- Record, per processing purpose, the purpose, the legal basis claimed, the data kept and the deletion
  trigger. Draft mapping for the owner and counsel to correct:

| Processing | Data | Purpose | Deletion trigger |
|---|---|---|---|
| Collect public posts and comments for one mission or watchlist run | Text excerpt, source link without account, publication date, counters | The user's own market research | Mission or watchlist deletion; 13 months after collection unless a retained claim cites it (Spec 016 FR-014) |
| Count distinct voices | Per-mission encrypted marker | Avoid counting one voice twice | Destroyed with the mission's evidence (Principle VII) |
| Declared accounts | Account the requester names for one mission | Study a brand's own account | Withdrawal by the requester, or mission deletion |
| Semantic judgment by the host model and TypeSafe | The fields a judgment needs | Relevance and support scoring | Not stored by Ignis beyond the judgment row |

- Implement the explicit retention action of Spec 016 FR-014 (backlog CMP-2) under the owner's
  migration gate, never on a schedule.
- Add a publish gate that scans quotes for residual personal data and asks for explicit confirmation
  before an artifact leaves the machine (backlog CMP-3).

## Questions only counsel or the owner can answer

- Does processing publicly posted content for the user's own research need consent, or does another
  basis apply (Articles on lawful bases; the alert cites none that exempts public content)?
- Does Article 20's impact assessment apply when data passes to a host model provider or TypeSafe
  outside Vietnam?
- Does Article 30 require Ignis's AI-assisted judgments to be risk-classified, and by whom?
- Does the five-year DPO exemption for small businesses and startups (Article 38) cover the owner?

## Consequences

- Until the owner accepts this record, Ignis's processing has no written legal basis; nothing in this
  draft changes behaviour.
- CMP-2 and CMP-3 stay blocked on the owner's acceptance of the deletion triggers above.
