import re
import unicodedata


def normalize_cluster_name(name: str) -> str:
    """
    Standard canonical cluster name normalization:
    1. Unicode Normalization Form C (NFC).
    2. Collapse sequential whitespaces into a single space and strip leading/trailing spaces.
    3. Lowercase for consistent deterministic grouping and UUIDv5 seed generation.
    """
    if not name:
        return ""
    nfc = unicodedata.normalize("NFC", name)
    collapsed = re.sub(r"\s+", " ", nfc).strip()
    return collapsed.lower()
