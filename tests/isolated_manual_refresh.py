"""Run the manual reference-check and publish sequence on a disposable data copy."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from bench_frontend_round2 import ROOT, copy_data


def main():
    with tempfile.TemporaryDirectory(prefix="etf-manual-refresh-") as temporary:
        data = Path(temporary)
        old = copy_data(data)
        child = """import json,sqlite3
from scripts.daily_verified import run_daily
from scripts.update_data import update_dataset
from scripts.config import DATABASE_PATH,DATA_ROOT
report=run_daily(database=DATABASE_PATH,data_root=DATA_ROOT,through='20261118',publish=False)
print(json.dumps({'phase':'verification','checked':sum(v['status']=='CHECKED' for v in report['indexes'].values()),'statuses':{k:{'status':v['status'],'route_approval':v.get('route_approval')} for k,v in report['indexes'].items()}},ensure_ascii=False),flush=True)
summary=update_dataset(require_reference_verification=True,end_date=report['through'])
print(json.dumps({'phase':'publication','summary':summary},ensure_ascii=False),flush=True)
with sqlite3.connect(DATABASE_PATH) as connection:
  issues=connection.execute("SELECT symbol,issue_code,COUNT(*) FROM quality_issues WHERE trade_date='20261118' AND kind='index' AND resolution_status='open' GROUP BY symbol,issue_code ORDER BY symbol").fetchall()
  refs=connection.execute("SELECT b.index_code,MAX(o.trade_date) FROM index_reference_batches b JOIN index_reference_observations o ON b.batch_id=o.batch_id WHERE b.status='FETCHED' GROUP BY b.index_code ORDER BY b.index_code").fetchall()
  prices=connection.execute("SELECT index_code,MAX(trade_date) FROM index_prices GROUP BY index_code ORDER BY index_code").fetchall()
print(json.dumps({'phase':'diagnostic','issues':issues,'reference_tails':refs,'published_tails':prices},ensure_ascii=False),flush=True)
"""
        env = {**os.environ, "ETF_DATA_DIR": str(data), "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.run([sys.executable, "-B", "-c", child], cwd=ROOT, env=env,
                                 text=True, capture_output=True, timeout=900)
        print(json.dumps({"old_snapshot_id": old["snapshot_id"], "exit_code": process.returncode,
                          "stdout": process.stdout, "stderr_tail": process.stderr[-3000:]}, ensure_ascii=False))
        if process.returncode:
            raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
