---
name: fn-ignis-harness
description: Route an explicit Ignis task to bounded social evidence collection or evidence-grounded Market analysis. Use when an agent needs the Ignis capability map.
---

# Ignis capability router

Ignis begins work only when assigned a specific task. It does not run an unattended trend radar,
daily discovery, or scheduled baseline. The two independent capabilities are:

- [Ignis collection](../ignis-collect/SKILL.md): source-specific probes or a bounded, inspectable
  multi-source mission. Collection can finish without a strategic verdict.
- [Ignis analysis](../ignis-analyze/SKILL.md): test a confirmed Market hypothesis against
  mission-scoped social evidence and render only claims admitted by the persisted Claim Ledger.

Read the applicable skill and current MCP tool descriptions before invoking a tool. Atomic
connector tools remain available independently. A file or purchased dataset without qualified
mission provenance is context, not primary Market evidence. Return an explicit Gap Report when
the evidence cannot support a verdict.

The governing product and tool contract is `specs/011-evidence-grounded-product-reset/`; this
router does not create a competing workflow or claim that an unreleased branch is deployed.
