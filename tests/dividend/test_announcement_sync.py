import hashlib

import pandas as pd
import pytest

from scripts.config import ROOT
from scripts.dividend.announcement_sync import (
    archive_etf_pdf, candidate_detail, normalize_etf_announcements, normalize_stock_dividends,
    sync_candidates,
)
from scripts.dividend.db import connect


def etf_frame():
    return pd.DataFrame([{'基金代码': '510880', '公告标题': '上证红利ETF分红公告',
                          '公告日期': '2026-01-16', '报告ID': 'AN202601151817055507'}])


def test_etf_directory_has_stable_pdf_candidate_without_promoting_event():
    row = normalize_etf_announcements(etf_frame(), 'ETF:510880')[0]
    assert row['archive_url'] == 'https://pdf.dfcfw.com/pdf/H2_AN202601151817055507_1.pdf'
    assert row['verification_level'] == 'UNVERIFIED'
    with pytest.raises(ValueError, match='混入'):
        normalize_etf_announcements(etf_frame(), 'ETF:510050')


def test_stock_cninfo_record_keeps_raw_per_ten_and_no_document_url():
    frame = pd.DataFrame([{'实施方案公告日期': '2026-06-22', '派息比例': 280.2423,
                           '除权日': '2026-06-26', '实施方案分红说明': '10派280.2423元(含税)',
                           '报告时间': '2025年报'}])
    row = normalize_stock_dividends(frame, 'STOCK:600519')[0]
    assert row['raw_cash_per_10'] == '280.2423'
    assert row['report_period'] == '2025年报'
    assert row['source_document_url'] is None


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, content):
        self.content = content

    def get(self, url, timeout):
        assert url.startswith('https://pdf.dfcfw.com/pdf/')
        assert timeout == 20
        return Response(self.content)


def test_pdf_archive_is_hashed_idempotent_and_html_is_rejected(tmp_path):
    row = normalize_etf_announcements(etf_frame(), 'ETF:510880')[0]
    payload = (ROOT / 'data' / 'raw' / 'dividend' / '510880_20260116_DSHH.pdf').read_bytes()
    first = archive_etf_pdf(row, tmp_path, session=Session(payload))
    second = archive_etf_pdf(row, tmp_path, session=Session(payload))
    assert first['pdf_sha256'] == second['pdf_sha256'] == hashlib.sha256(payload).hexdigest()
    assert len(list(tmp_path.glob('*.pdf'))) == 1
    with pytest.raises(ValueError, match='PDF'):
        archive_etf_pdf(row, tmp_path, session=Session(b'<html>captcha</html>'))


def test_sync_persists_candidates_only(tmp_path):
    db = tmp_path / 'candidate.sqlite'
    root = tmp_path / 'raw' / 'dividend' / 'announcements'
    rows = normalize_etf_announcements(etf_frame(), 'ETF:510880')
    payload = (ROOT / 'data' / 'raw' / 'dividend' / '510880_20260116_DSHH.pdf').read_bytes()
    result = sync_candidates(db, 'ETF:510880', root, fetcher=lambda _: rows,
                             session=Session(payload))
    assert result['pdf_count'] == 1
    assert result['status'] == 'CANDIDATES_ONLY'
    detail = candidate_detail(db, 'ETF:510880')
    assert detail['items'][0]['pdf_sha256'] == hashlib.sha256(payload).hexdigest()
    assert 'local_file' not in detail['items'][0]
    class OfflineSession:
        def get(self, *args, **kwargs):
            raise AssertionError('cached PDF was downloaded again')
    repeated = sync_candidates(db, 'ETF:510880', root, fetcher=lambda _: rows,
                               session=OfflineSession())
    assert repeated['pdf_count'] == 1
    with connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM raw_source_records').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM dividend_events').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM dividend_quotes').fetchone()[0] == 0
