"""Capture official index factsheets as separate identity evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

from pypdf import PdfReader
import requests

from .config import DATA_ROOT, INDEXES
from .index_verification import OFFICIAL_IDENTITY, CSI_FACTSHEETS

CNI_FACTSHEETS = {
    "480080": "https://www.cnindex.com.cn/html2pdf/preview/jj_980080.pdf",
    "480081": "https://www.cnindex.com.cn/html2pdf/preview/jj_980081.pdf",
}


def collect(output=DATA_ROOT / "verification" / "identity"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    entries = {}
    for code in INDEXES:
        url = OFFICIAL_IDENTITY.get(code) or CNI_FACTSHEETS[code]
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError("not a PDF")
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
            if code not in text:
                raise ValueError("index code absent from factsheet")
            digest = hashlib.sha256(raw).hexdigest()
            path = output / f"{digest}.pdf"
            if not path.exists():
                path.write_bytes(raw)
            entries[code] = {"status":"CAPTURED","source_url":url,"sha256":digest,
                             "path":str(path),"bytes":len(raw),"base_date_claim":CSI_FACTSHEETS.get(code,(None,"20121231"))[1]}
        except Exception as exc:
            entries[code] = {"status":"UNAVAILABLE","source_url":url,"error_type":type(exc).__name__}
    result = {"collected_at":datetime.now(timezone.utc).isoformat(),"indexes":entries}
    (output / "identity-evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


if __name__ == "__main__":
    result=collect()
    print(json.dumps({code:item["status"] for code,item in result["indexes"].items()},ensure_ascii=False))
