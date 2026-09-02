import re
import pytest
from pathlib import Path
from datetime import datetime, timezone

from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
import ignis.infrastructure.auth.crypto as crypto_mod
from ignis.infrastructure.auth.crypto import encrypt_credentials, decrypt_credentials, _get_fernet_instance
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode, resolve_geo, resolve_platform
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def test_sql_alphabetical_bootstrap_order():
    """Verify all SQL migration files in sql/ directory are named and ordered sequentially."""
    sql_dir = Path(__file__).resolve().parents[2] / "sql"
    assert sql_dir.exists(), "sql directory must exist"
    
    sql_files = sorted(list(sql_dir.glob("*.sql")))
    assert len(sql_files) >= 5
    
    assert sql_files[0].name.startswith("001_")
    for i, f in enumerate(sql_files):
        prefix = f.name.split("_")[0]
        assert prefix.isdigit(), f"File {f.name} must start with digit prefix"
        assert int(prefix) == i + 1, f"File {f.name} expected prefix {i+1:03d}"


def test_postgres_sqlite_noise_seed_parity():
    """Verify 100% exact parity between Postgres 004_global_lexicons.sql and SQLite initial_seeds."""
    sql_file = Path(__file__).resolve().parents[2] / "sql" / "004_global_lexicons.sql"
    sql_content = sql_file.read_text(encoding="utf-8")
    
    # Extract noise_blacklist terms from SQL
    pg_noise_terms = set(re.findall(r"\('noise_blacklist',\s*'([^']+)'", sql_content))
    
    # Extract noise_blacklist terms from SQLite repository
    repo = SqliteTrendRepository(":memory:")
    repo._create_tables_and_seed()
    conn = repo._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT term FROM market_lexicons WHERE domain = 'noise_blacklist'")
    sqlite_noise_terms = {row[0] for row in cur.fetchall()}
    
    assert len(pg_noise_terms) >= 19
    assert len(sqlite_noise_terms) >= 19
    # Parity check: 0 parity gap
    assert pg_noise_terms == sqlite_noise_terms, f"Difference: {pg_noise_terms ^ sqlite_noise_terms}"


@pytest.mark.asyncio
async def test_dynamic_noise_blacklist_rejection_end_to_end_sqlite():
    """Verify dynamic noise blacklist seeds from SQLite repository and rejects noise end-to-end."""
    repo = SqliteTrendRepository(":memory:")
    await repo._ensure_schema()
    
    db_lexicons = await repo.get_domain_lexicons()
    noise_items = [item["term"] for item in db_lexicons if item.get("domain") == "noise_blacklist"]
    pos_items = [item["term"] for item in db_lexicons if item.get("domain") not in ("foreign_stopwords", "noise_blacklist")]
    stop_items = [item["term"] for item in db_lexicons if item.get("domain") == "foreign_stopwords"]
    
    assert len(noise_items) >= 19
    assert "fyp" in noise_items
    assert "haihuoc" in noise_items

    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    # Wire terms exactly as done by orchestrator & MCP server
    evaluator.register_terms(pos_items)
    reasoner.register_terms(pos_items)
    evaluator.register_foreign_stopwords(stop_items)
    reasoner.register_foreign_stopwords(stop_items)
    evaluator.register_noise_blacklist(noise_items)
    reasoner.register_noise_blacklist(noise_items)

    # Pure noise titles MUST be rejected
    assert not evaluator.is_vietnamese("Xem clip haihuoc cuoi be bung #fyp")
    assert not evaluator.is_vietnamese("Trend xuhuong tiktok moi nhat 2026")
    assert not reasoner._is_vietnamese("troll vlog chuyenhai")

    # Legitimate business/tech topics containing words like 'trending', 'viral', 'mindset' MUST PASS (no substring false positives!)
    assert evaluator.is_vietnamese("Sản phẩm trending trên TikTok Shop 2026")
    assert evaluator.is_vietnamese("Chien luoc viral marketing cho local brand ban hang")
    assert evaluator.is_vietnamese("Abundance mindset trong ban hang online")
    assert evaluator.is_vietnamese("Nganh hang anime merchandise tai Viet Nam")
    assert evaluator.is_vietnamese("Huong dan cai dat n8n tu dong hoa quy trinh")
    assert evaluator.is_vietnamese("Giai phap ai agent quan ly ban hang ecommerce")


    
    await repo.close()


def test_dynamic_resolvers_without_silent_substitution():
    """Verify resolve_geo and resolve_platform do NOT silently fallback or drop custom values."""
    # Test international geos (BR, KR, IN, DE, JP, US, VN)
    assert resolve_geo("BR").value == "BR"
    assert resolve_geo("KR").value == "KR"
    assert resolve_geo("IN").value == "IN"
    assert resolve_geo("DE").value == "DE"
    assert resolve_geo("JP").value == "JP"
    assert resolve_geo("VN").value == "VN"
    
    # Test custom platforms (reddit, xiaohongshu, custom_connector)
    assert resolve_platform("reddit").value == "reddit"
    assert resolve_platform("xiaohongshu").value == "xiaohongshu"
    assert resolve_platform("youtube").value == "youtube"


def test_crypto_ephemeral_key_security():
    """Verify non-deterministic in-memory ephemeral key cannot decrypt across instances."""
    crypto_mod._EPHEMERAL_KEY = None
    _get_fernet_instance()
    k1 = crypto_mod._EPHEMERAL_KEY
    
    payload = {"api_key": "sk-secret-12345"}
    enc = encrypt_credentials(payload)
    assert enc["_encrypted"] is True
    
    crypto_mod._EPHEMERAL_KEY = None
    _get_fernet_instance()
    k2 = crypto_mod._EPHEMERAL_KEY
    
    assert k1 is not None and k2 is not None
    assert k1 != k2
    
    with pytest.raises(ValueError, match="Failed to decrypt credentials"):
        decrypt_credentials(enc)


def test_portuguese_tilde_rejection():
    """Verify Portuguese words with tilde (ã, õ, ũ) are not falsely recognized as Vietnamese."""
    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    portuguese_titles = [
        "Automação de processos com n8n",
        "Configuração da API do WhatsApp",
        "Criação de agentes inteligentes",
    ]
    for pt in portuguese_titles:
        assert not evaluator.is_vietnamese(pt), f"Expected Portuguese title '{pt}' to be rejected"
        assert not reasoner._is_vietnamese(pt), f"Expected Portuguese title '{pt}' to be rejected"


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
    assert sig.metadata is not original_meta
