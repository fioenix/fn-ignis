# Claim Ledger example

The current `frame_digest` identifies one confirmed Brief, collection plan, observations,
qualifications, and channel outcomes. One candidate claim binds a qualified observation with
`SUPPORT` for `core`; another binds qualified counterevidence with `CONTRADICTION` for
`alternative:1`. A purchased CSV is `CONTEXT_ONLY` until an authorized mission verifies and
qualifies its records.

A candidate with no valid binding is withheld. If the frame fails sufficiency, the response is a
Gap Report; it names what is missing and a bounded next probe. The agent can describe a safe partial
observation, but cannot turn the unsupported candidate into a recommendation.
