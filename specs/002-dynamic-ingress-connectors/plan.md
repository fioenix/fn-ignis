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
- **Error Isolation**: Tích hợp với `CircuitBreaker` từ `ConnectorPluginRegistry`
- **Testing**: `pytest`, `pytest-asyncio` với mock responses

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
