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

    # 3. Redact Vietnamese Phones
    sanitized = VN_PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)

    # 4. Redact Structured International Formatted Phones
    sanitized = INTERNATIONAL_FORMATTED_PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)

    return sanitized


def sanitize_pii_data(data: Union[Dict[str, Any], List[Any], str]) -> Union[Dict[str, Any], List[Any], str]:
    """Recursively sanitize dictionary, list, or string structures."""
    if isinstance(data, str):
        return sanitize_pii_text(data)
    elif isinstance(data, dict):
        return {k: sanitize_pii_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_pii_data(item) for item in data]
    return data
