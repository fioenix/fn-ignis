import re
from typing import Any, Dict, List, Union

# Regex patterns for high-risk PII identification
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    re.IGNORECASE
)

# Vietnamese & International Phone Number Pattern
VN_PHONE_PATTERN = re.compile(
    r"(?:(?:\+84|0084|84|\(\+84\))\s*|\b0)[235789](?:[\s\.\-]*\d){8}\b"
)

# Generic multi-digit continuous phone sequences (10-11 digits)
GENERIC_PHONE_SEQUENCE = re.compile(
    r"\b(?:\+?[0-9]{1,3}[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"
)

# Secrets and token patterns (OpenAI sk-, GitHub ghp_, JWT tokens)
SECRET_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})\b"
)


def sanitize_pii_text(text: str) -> str:
    """
    Sanitize PII (Personal Identifiable Information) from input text.
    Redacts phone numbers, emails, and API credentials to prevent leaks in compliance with GDPR & Privacy Laws.
    """
    if not text or not isinstance(text, str):
        return text

    sanitized = text
    # 1. Redact Emails
    sanitized = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)
    
    # 2. Redact Secrets
    sanitized = SECRET_PATTERN.sub("[REDACTED_SECRET]", sanitized)

    # 3. Redact Vietnamese Phones (including formatted and dotted numbers)
    sanitized = VN_PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)

    # 4. Redact Generic Continuous Phone sequences
    sanitized = GENERIC_PHONE_SEQUENCE.sub("[REDACTED_PHONE]", sanitized)

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
