from scripts.dividend.db import connect, init_schema, upsert_security
from scripts.dividend.service import history_detail


def test_history_as_known_keeps_later_revision_out_of_earlier_point(tmp_path):
    path = tmp_path / 'pit.sqlite'
    init_schema(path)
    upsert_security(path, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                           'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    with connect(path) as db:
        doc = db.execute("""INSERT INTO source_documents
            (source_id,title,publisher,url,sha256,verification_level)
            VALUES ('official','公告','交易所','https://example.test','verified-hash','OFFICIAL_VERIFIED')""").lastrowid
        db.execute("INSERT INTO dividend_events VALUES ('event','ETF:510880',NULL,'2026-01-20','0.2','PAID','r2')")
        db.executemany('''INSERT INTO dividend_revisions
            (revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status,source_document_id,ex_date)
            VALUES (?,?,?,?,?,?,?,?,?)''', [
                ('r1','event','2026-01-10','2026-01-10','1.0','PER_10','PAID',doc,'2026-01-20'),
                ('r2','event','2026-02-01','2026-02-01','2.0','PER_10','PAID',doc,'2026-01-20'),
            ])
        db.executemany('''INSERT INTO dividend_quotes
            (security_id,trade_date,price,source_id,verification_level) VALUES (?,?,?,?,?)''', [
                ('ETF:510880','2026-01-21','2.0','fixture','VERIFIED_UNADJUSTED'),
                ('ETF:510880','2026-02-02','2.0','fixture','VERIFIED_UNADJUSTED'),
            ])
        db.execute('''INSERT INTO dividend_coverage
            (security_id,start_date,end_date,evidence_sha256,verified_at,
             dividends_complete,actions_verified,quote_calendar_verified,query_mode)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('ETF:510880','2025-01-01','2026-02-02','verified-hash','2026-02-03',1,1,1,'as_known'))
    result = history_detail(path, 'ETF:510880', '1Y', 'as_known')
    assert [row['ttm_pct'] for row in result['rows']] == ['5.0000', '10.0000']
    assert result['coverage_status'] == 'INCOMPLETE'  # Two days cannot stand in for a full year.
