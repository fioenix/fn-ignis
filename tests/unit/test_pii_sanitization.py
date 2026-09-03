import re
from pathlib import Path
from ignis.infrastructure.security.pii_sanitizer import (
    sanitize_pii_text,
    sanitize_pii_data,
)


def test_sanitize_phone_numbers_and_emails():
    sample_text = (
        "Xưởng may áo linen nam giá sỉ 0931405002 và 0938940397. "
        "Liên hệ tư vấn (+84) 931 405 002 hoặc 0938.940.397. "
        "Gửi mail: support@fashion-vn.com, key: sk-1234567890abcdef1234567890"
    )
    cleaned = sanitize_pii_text(sample_text)
    
    assert "0931405002" not in cleaned
    assert "0938940397" not in cleaned
    assert "0938.940.397" not in cleaned
    assert "support@fashion-vn.com" not in cleaned
    assert "sk-1234567890abcdef1234567890" not in cleaned
    assert "[REDACTED_PHONE]" in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "[REDACTED_SECRET]" in cleaned


def test_sanitize_pii_data_recursive():
    nested_data = {
        "title": "Áo thun hotline 0931405002",
        "comments": [
            {"author": "user1", "text": "Call me 0938.940.397 please"},
            {"author": "user2", "text": "Contact me at sales@company.vn"},
        ],
        "meta": {"nested_phone": "(+84) 931 405 002"},
    }
    cleaned_data = sanitize_pii_data(nested_data)
    
    assert "[REDACTED_PHONE]" in cleaned_data["title"]
    assert "[REDACTED_PHONE]" in cleaned_data["comments"][0]["text"]
    assert "[REDACTED_EMAIL]" in cleaned_data["comments"][1]["text"]
    assert "[REDACTED_PHONE]" in cleaned_data["meta"]["nested_phone"]


def test_tracked_reference_reports_have_zero_pii():
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    if not reports_dir.exists():
        return

    phone_re = re.compile(r"(?:(?:\+84|0084|84|\(\+84\))\s*|\b0)[235789](?:[\s\.\-]*\d){8}\b")
    email_re = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

    for report_file in reports_dir.glob("case_study_*.html"):
        content = report_file.read_text(encoding="utf-8")
        phones = phone_re.findall(content)
        emails = email_re.findall(content)
        assert len(phones) == 0, f"PII phone leak in {report_file.name}: {phones}"
        assert len(emails) == 0, f"PII email leak in {report_file.name}: {emails}"
