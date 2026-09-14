# Implementation Plan: Dynamic Ingress Connectors (TikTok, Threads, Instagram Reels)

**Feature Directory**: `specs/002-dynamic-ingress-connectors`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Summary

Xây dựng 3 Ingress Connectors cho TikTok, Threads và Instagram Reels kế thừa `IConnectorPlugin`, sử dụng `httpx` async với headers/cookies tối ưu và deterministic parsing để đảm bảo Zero-Token Ingress.

---

## Technical Context

- **Protocol**: HTTP/2 & JSON parsing qua `httpx`
- **Runtime tiers**: official HTTP APIs when configured; operator-side Playwright for browser-only
  surfaces. The unattended worker registers only runtimes available in its image.
- **Error Isolation**: Tích hợp với `CircuitBreaker` từ `ConnectorPluginRegistry`
- **Testing**: `pytest`, `pytest-asyncio` với mock responses
- **Identity boundary**: connectors expose identifiers and permalinks; the shared domain resolver
  maps them into namespaced external identities. Titles never participate in identity.

---

## Structure

```text
src/ignis/infrastructure/connectors/
├── tiktok/
│   ├── __init__.py
│   └── tiktok_plugin.py
├── threads/
│   ├── __init__.py
│   └── threads_plugin.py
└── reels/
    ├── __init__.py
    └── reels_plugin.py
```
