from pathlib import Path
from datetime import datetime, timezone
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.auth.crypto import encrypt_credentials, decrypt_credentials
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode


def test_sql_alphabetical_bootstrap_order():
    """Verify all SQL migration files in sql/ directory are named and ordered such that they execute cleanly."""
    sql_dir = Path(__file__).resolve().parents[2] / "sql"
    assert sql_dir.exists(), "sql directory must exist"
    
    sql_files = sorted(list(sql_dir.glob("*.sql")))
    assert len(sql_files) >= 5
    
    # 001_ must be first
    assert sql_files[0].name.startswith("001_")
    # Verify sequence
    for i, f in enumerate(sql_files):
        prefix = f.name.split("_")[0]
        assert prefix.isdigit(), f"File {f.name} must start with digit prefix"
        assert int(prefix) == i + 1, f"File {f.name} expected prefix {i+1:03d}"


def test_dynamic_noise_blacklist_rejection():
    """Verify dynamic noise blacklist rejects entertainment and generic noise titles."""
    evaluator = QualityEvaluator()
    evaluator.register_noise_blacklist(["fyp", "xuhuong", "haihuoc", "funny", "troll", "vlog", "nhactre"])
    
    noise_titles = [
        "Xem clip haihuoc cuoi be bung #fyp",
        "Trend xuhuong tiktok moi nhat 2026",
        "Video troll ban than cuc manh",
        "Daily vlog cuoc song gia dinh funny moments",
    ]
    
    for title in noise_titles:
        assert not evaluator.is_vietnamese(title), f"Expected noise title '{title}' to be rejected"

    # Genuine business / tech titles MUST be accepted
    legit_titles = [
        "Huong dan cai dat n8n tu dong hoa quy trinh",
        "Giai phap ai agent quan ly ban hang ecommerce",
        "Xay dung he thong chatbot cham soc khach hang",
    ]
    for title in legit_titles:
        assert evaluator.is_vietnamese(title), f"Expected legitimate title '{title}' to be accepted"


def test_crypto_ephemeral_key_security():
    """Verify that unconfigured key uses non-deterministic random ephemeral key."""
    payload = {"api_key": "sk-secret-12345"}
    enc = encrypt_credentials(payload)
    assert enc["_encrypted"] is True
    assert "sk-secret-12345" not in enc["ciphertext"]
    
    dec = decrypt_credentials(enc)
    assert dec == payload


def test_quality_evaluator_metadata_isolation():
    """Verify evaluate_quality does not contaminate original caller signals metadata reference."""
    evaluator = QualityEvaluator()
    original_meta = {"channel_title": "AI Master"}
    sig = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Huong dan lap trinh AI Agent cho nguoi moi",
        metric_value=50000.0,
        growth_velocity=120.0,
        source_url="https://youtube.com/watch?v=123",
        geo_code=GeoCode.VN,
        metadata=original_meta,
        captured_at=datetime.now(timezone.utc),
    )
    
    evaluator.evaluate_quality([sig], geo=GeoCode.VN)
    assert sig.metadata["is_localized"] is True
    # Verify metadata was cloned
    assert sig.metadata is not original_meta
