import re
from typing import Any, Dict, List, Union

# Regex patterns for high-risk PII identification
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    re.IGNORECASE
)

# Vietnamese Phone Number Pattern (e.g., 0931405002, 0931.405.002, +84 931 405 002, (+84) 938-940-397)
VN_PHONE_PATTERN = re.compile(
    r"(?:(?:\+84|0084|84|\(\+84\))\s*|\b0)[235789](?:[\s\.\-]*\d){8}\b"
)

# Structured International Formatted Phone Numbers (Requires explicit delimiters or '+' country prefix)
# Does NOT match plain unformatted large numbers (e.g., 1234567890 views, 1000000000 VND)
INTERNATIONAL_FORMATTED_PHONE_PATTERN = re.compile(
    r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?|\b\d{2,4}[\s.\-])\d{3,4}[\s.\-]\d{3,4}\b"
)

# Secrets and token patterns (OpenAI sk-, GitHub ghp_, JWT tokens)
SECRET_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})\b"
)

# Operational errors often echo a request URL or an OAuth form. The value shape is provider-
# specific, so the field name is the reliable signal; keeping the name makes diagnostics useful
# while ensuring the credential itself never reaches logs, outcomes, or persisted audit details.
NAMED_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"authorization|password|key)\s*[:=]\s*)(?!\[REDACTED_SECRET\])"
    r"((?:Bearer\s+)?[^&\s,;]+)"
)
BEARER_SECRET_PATTERN = re.compile(r"(?i)(\bBearer\s+)(?!\[REDACTED_SECRET\])([^\s,;]+)")
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "client_secret",
        "clientsecret",
        "authorization",
        "password",
        "key",
    }
)

# Evidence identities can resemble formatted phone numbers. Keep their exact bytes for
# citation resolution, but only after secret-field and credential redaction has run.
UUID_PATTERN = re.compile(
    r"(\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b)",
    re.IGNORECASE,
)


def sanitize_pii_text(text: str) -> str:
    """
    Sanitize PII (Personal Identifiable Information) from input text.
    Redacts phone numbers, emails, and API credentials to prevent leaks in compliance with GDPR & Privacy Laws.
    Preserves numerical metrics, view counts, and financial transaction amounts.
    """
    if not text or not isinstance(text, str):
        return text

    sanitized = text
    # 1. Redact Emails
    sanitized = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)
    
    # 2. Redact Secrets
    sanitized = SECRET_PATTERN.sub("[REDACTED_SECRET]", sanitized)
    sanitized = NAMED_SECRET_PATTERN.sub(r"\1[REDACTED_SECRET]", sanitized)
    sanitized = BEARER_SECRET_PATTERN.sub(r"\1[REDACTED_SECRET]", sanitized)

    # Phone matching must not consume a fragment of a canonical evidence UUID.
    parts = UUID_PATTERN.split(sanitized)
    for index in range(0, len(parts), 2):
        parts[index] = VN_PHONE_PATTERN.sub("[REDACTED_PHONE]", parts[index])
        parts[index] = INTERNATIONAL_FORMATTED_PHONE_PATTERN.sub(
            "[REDACTED_PHONE]", parts[index]
        )
    sanitized = "".join(parts)

    return sanitized


def sanitize_pii_data(data: Union[Dict[str, Any], List[Any], str]) -> Union[Dict[str, Any], List[Any], str]:
    """Recursively sanitize dictionary, list, or string structures."""
    if isinstance(data, str):
        return sanitize_pii_text(data)
    elif isinstance(data, dict):
        return {
            k: (
                "[REDACTED_SECRET]"
                if str(k).replace("-", "_").casefold() in SENSITIVE_FIELD_NAMES
                else sanitize_pii_data(v)
            )
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [sanitize_pii_data(item) for item in data]
    return data
