import json
from decimal import Decimal
from pathlib import Path


MANIFEST = Path(__file__).parents[2] / 'data' / 'raw' / 'dividend' / 'evidence_manifest.json'


def test_510880_golden_fields_and_hash_are_fixed():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    item = next(row for row in manifest['records'] if row['security_id'] == 'ETF:510880')
    assert item['verification_status'] == 'official_source_downloaded'
    assert Decimal(item['fields']['raw_amount']) / Decimal('10') == Decimal('0.14300')
    assert item['fields']['ex_date'] == '2026-01-21'
    assert len(item['sha256']) == 64


def test_600519_is_not_mislabeled_as_official_when_static_sse_file_is_blocked():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    item = next(row for row in manifest['records'] if row['security_id'] == 'STOCK:600519')
    assert item['verification_status'] == 'mirror_only_official_url_unavailable'
    assert Decimal(item['fields']['amount_per_share']) == Decimal('28.02423')
    assert item['fields']['ex_date'] == '2026-06-26'
