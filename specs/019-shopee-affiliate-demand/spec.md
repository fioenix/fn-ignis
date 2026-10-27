# Feature Specification: Shopee Affiliate Demand Channel

**Feature Branch**: `claude/shopee-affiliate-spec`

**Created**: 2026-10-27

**Status**: Draft, waiting on the owner's account checks (see "Gates before planning"). Not ready
for clarification or planning until all three gates pass.

**Input**: User description: "Soạn spec phác thảo cho Shopee Affiliate chờ tao kiểm tài khoản." (Draft
a spec for a Shopee Affiliate channel that waits for the owner to check the account.)

## Outcome and audience

A person following a watchlist (Spec 016) hears what social channels show about a product topic,
but not whether people buy it. The commerce spike of 26/10/2026 and the Shopee survey of the same
day found one official, individual-usable source of cross-shop sales on Shopee Vietnam: the Shopee
Affiliate Open API (`productOfferV2`), which returns products by keyword or category, sorted by
units sold, with cumulative sales, price range, rating and category ids. The decision this
supports is the same as the watchlist's: is demand for this topic moving between two periods,
now with a purchase signal next to the attention signal.

The observable proof is a watchlist run that collects a Shopee snapshot for each topic keyword,
and a period view that reports units sold between snapshots for that keyword, labelled as an
affiliate sample.

## Context: current state (observed 27/10/2026 on `main` at `d0f562c`)

- Ignis has no commerce channel. The source map in `BACKLOG.md` lists Shopee's Affiliate Open API
  as the only candidate (PR #85, open); the seller Open Platform covers one's own shop only.
- Shopee VN terms of service, section 3.1 (published 22/09/2026), forbid monitoring, compiling or
  collecting Shopee content by automated or manual means without prior written consent;
  `robots.txt` blocks `/top_products`. Reading Shopee pages through any browser, including the host
  browser search of Spec 012, is therefore out of scope. An API licence is the written consent the
  terms require.
- Facts about the Affiliate Open API come from a third-party document for the VN edition; the
  official documentation at `affiliate.shopee.vn/open_api` requires a login. Open API access is
  granted separately from an affiliate account (error code 10035, third-party report).
- A watchlist run is one snapshot per channel (Spec 018); the seen axis averages per snapshot and
  judges coverage against the user's recorded cadence.

## Gates before planning

The owner checks these on a real account; this spec moves to clarification only when all pass.

- **G1 Access**: a Shopee Affiliate VN account exists and Open API access is granted.
- **G2 Terms**: the Affiliate Open API terms allow storing and analysing offer data, not only
  promoting links. If they allow promotion only, this feature stops.
- **G3 Fields**: one test call with a G3 keyword ("áo khoác chống nắng") and one category confirms
  that sorting by sales and the "Top performing" list exist in VN, that `sales` is returned per
  product, and that results match shopping intent by eye.

If a gate fails, the feature stops; there is no scraping or browser fallback.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Collect a Shopee snapshot in a watchlist run (Priority: P1)

A person adds `shopee_affiliate` to a watchlist run's allowed channels. For each topic keyword, the
run asks the Affiliate Open API for the products it returns sorted by units sold, and stores one
observation per product: product id, product name, category ids, price range, rating and
cumulative units sold at that moment.

**Why this priority**: every later reading needs stored snapshots; one snapshot alone already shows
which products lead a keyword.

**Independent Test**: run G3 with `shopee_affiliate` allowed; the run stores up to the per-keyword
limit of products for each keyword, each with cumulative sales and capture time, and no shop name.

**Acceptance Scenarios**:

1. **Given** credentials are configured and G3 is run with `shopee_affiliate`, **When** the run
   completes, **Then** each topic keyword has a completed Shopee outcome and its products are
   stored with cumulative sales.
2. **Given** credentials are missing, **When** the run asks for `shopee_affiliate`, **Then** the
   outcome is `AUTH_REQUIRED` and other channels are unaffected.
3. **Given** the day's request ceiling is reached, **When** another keyword is asked, **Then** the
   outcome is `RATE_LIMITED` with the keywords that were queried.

---

### User Story 2 - Read units sold between periods (Priority: P1)

The period view reports, per topic, the units sold between snapshots: for each product seen in two
snapshots, the change in its cumulative sales, summed per keyword and averaged per snapshot
interval; plus how many products led the keyword and their price bands. Every figure is labelled
as an affiliate sample.

**Why this priority**: cumulative sales say little; the movement between snapshots is the demand
signal.

**Independent Test**: with two snapshots a week apart for one keyword, the view reports the summed
sales change of products present in both, and lists products present in only one as entered or
left, without counting their sales.

**Acceptance Scenarios**:

1. **Given** product A shows 1,200 sold on 20/10 and 1,500 on 27/10, **When** the week is read,
   **Then** A contributes 300 units to its keyword.
2. **Given** a product absent from the earlier snapshot, **When** the period is read, **Then** it is
   counted as entering the list and contributes no units.
3. **Given** a product's sales value is rounded (for example "1k+"), **When** the change cannot be
   computed exactly, **Then** the product is reported as uncounted rather than estimated.

---

### User Story 3 - Labels that prevent over-reading (Priority: P2)

The view and any claim built on it state that the sample covers only products enrolled in the
affiliate programme, that commission can influence which products appear, and that the figures are
not "Shopee Top Bán Chạy".

**Why this priority**: the sample bias is structural; without the label a reader would take it as
the marketplace ranking.

**Independent Test**: every Shopee figure in a period view and in a rendered report carries the
affiliate-sample label.

**Acceptance Scenarios**:

1. **Given** a period view with Shopee figures, **When** it is rendered, **Then** each figure states
   the affiliate-sample basis.
2. **Given** a market claim cites Shopee evidence, **When** the Claim Ledger is written, **Then** the
   sample limitation is recorded as a gap.

---

### Edge Cases

- A product delisted between snapshots: it leaves the list; no negative sales are recorded.
- Cumulative sales that decrease (refunds or recounts): the change is reported as uncounted.
- A keyword that returns no products: `EMPTY_NO_DATA` with the queried keyword.
- The same product returned for two keywords of one topic: counted once per topic.
- Shopee changes the field or rounding format: the outcome is `DEGRADED` with the reason, never a
  silent zero.
- Access revoked or terms changed after launch: the channel stops with `AUTH_REQUIRED` or is
  removed; no fallback path.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ignis MUST read Shopee only through the Shopee Affiliate Open API under the owner's
  granted access; it MUST NOT read Shopee pages, internal endpoints or seller tools by browser or
  HTTP.
- **FR-002**: A Shopee call MUST happen only inside an explicit mission or atomic probe, never in
  the background (Constitution I); per-day request ceilings apply as for other channels.
- **FR-003**: Each stored observation MUST hold product id, product name, category ids, price range,
  rating, cumulative units sold and capture time; it MUST NOT hold shop name or any person's name or
  handle (Constitution VII). [NEEDS CLARIFICATION: keep no shop identifier at all, or keep a
  per-mission marker of the shop id so a period view can say how concentrated sales are across
  shops?]
- **FR-004**: The products asked for per keyword MUST be bounded by a limit configured in the
  database (default 20, matching other channels), sorted by units sold.
- **FR-005**: The keywords queried MUST be the watchlist topic's keywords. [NEEDS CLARIFICATION:
  should a topic also be able to name Shopee category ids, held in the industry taxonomy, so the
  channel can read a category's leaders and not only keyword results?]
- **FR-006**: The period view MUST report units sold as the change in cumulative sales between
  snapshots of the same product, and MUST NOT estimate a change it cannot compute.
- **FR-007**: Every Shopee figure MUST carry the affiliate-sample label, and claims citing it MUST
  record the sample limitation as a gap.
- **FR-008**: Missing credentials, revoked access, rate limits and field changes MUST surface as
  the matching probe outcome status (`AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`), never as empty
  data.
- **FR-009**: Credentials MUST be read from the environment like other connectors and never logged
  or stored with evidence.
- **FR-010**: Behaviour MUST be identical on SQLite and PostgreSQL.
- **FR-011**: The channel MUST NOT be enabled unless gates G1, G2 and G3 have passed and are
  recorded in this spec. [NEEDS CLARIFICATION: before building the channel, run the 14-day spike of
  the commerce note (two watchlists, daily snapshots, pass if deltas move, rankings are stable and
  results match intent), or build the channel and treat its first 14 days as the spike?]

### Key Entities

- **Shopee offer observation**: one product as the Affiliate Open API returned it for one keyword in
  one snapshot, with cumulative units sold.
- **Units sold in a period**: the summed change in cumulative sales of products present in two
  snapshots of a keyword.
- **Affiliate sample**: the set of products enrolled in the affiliate programme; the only population
  this channel describes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After 14 daily snapshots of G3, at least 80 percent of products present on two
  consecutive days have a computable change in units sold.
- **SC-002**: No shop name or personal name or handle is found at rest after a Shopee run (the
  author-identity scan of Spec 015 passes).
- **SC-003**: A G3 run with `shopee_affiliate` stays within the channel's daily request ceiling.
- **SC-004**: 100 percent of Shopee figures in a period view carry the affiliate-sample label.
- **SC-005**: If any gate fails, no Shopee code path ships and the source map records why.

## Assumptions

- The third-party description of `productOfferV2` (filters `keyword`, `productCatId`, `listType`;
  `sortType` 2 for units sold; fields `sales`, `priceMin`, `priceMax`, `ratingStar`,
  `productCatIds`) holds for the VN edition; G3 confirms it.
- `sales` is cumulative and may be rounded; period movement therefore needs at least two snapshots
  per period, which the user's research cadence (Spec 018) already governs.
- Commission and enrolment bias the sample; the channel describes affiliate products only.
- Product names are product data, not author identity; shop names are excluded because a shop can
  be named after a person.
- Keywords and any category ids come from the watchlist definition and the database taxonomies, not
  from Python constants.
