"""Read-only, repeatable local API benchmark for the published market snapshot."""

import json
import hashlib
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path


def percentile(samples, proportion):
    ordered = sorted(samples)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * proportion + .999999) - 1))]


def main():
    source = Path(__file__).resolve().parents[1] / "data"
    manifest = json.loads((source / "current_manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="etf-a03-a04-") as temporary:
        root = Path(temporary)
        (root / "current_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for relative in manifest["files"].values():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        with closing(sqlite3.connect((source / "etf_market.db").as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(root / "etf_market.db")) as copy:
                original.backup(copy)
        os.environ["ETF_DATA_DIR"] = str(root)
        sys.path.insert(0, str(source.parent))
        from fastapi.testclient import TestClient
        import server

        segments = defaultdict(list)
        original_read = server.read_dataset
        original_build = server.build_overview

        def timed_read(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original_read(*args, **kwargs)
            finally:
                segments["snapshot_read_ms"].append((time.perf_counter() - started) * 1000)

        def timed_build(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original_build(*args, **kwargs)
            finally:
                segments["overview_compute_ms"].append((time.perf_counter() - started) * 1000)

        server.read_dataset = timed_read
        server.build_overview = timed_build
        routes = ["/api/snapshot/data/index_prices.json", "/api/rotation/overview"]
        if any(route.path == "/api/snapshot/index-view" for route in server.app.routes):
            routes += ["/api/snapshot/index-view?strategy=prism", "/api/snapshot/index-view?strategy=dividend-hs300"]
        with TestClient(server.app) as client:
            sqlite_connects, sqlite_queries = [], []
            original_connect = sqlite3.connect

            def traced_connect(*args, **kwargs):
                connection = original_connect(*args, **kwargs)
                sqlite_connects.append(1)
                connection.set_trace_callback(sqlite_queries.append)
                return connection

            sqlite3.connect = traced_connect
            try:
                for route in routes:
                    readings, query_counts, connect_counts = [], [], []
                    response = None
                    for _ in range(12):
                        before_queries, before_connects = len(sqlite_queries), len(sqlite_connects)
                        started = time.perf_counter()
                        response = client.get(route)
                        readings.append((time.perf_counter() - started) * 1000)
                        query_counts.append(len(sqlite_queries) - before_queries)
                        connect_counts.append(len(sqlite_connects) - before_connects)
                        if response.status_code != 200:
                            raise RuntimeError(f"{route}: {response.status_code} {response.text[:200]}")
                    print(json.dumps({"route": route, "n": len(readings), "p50_ms": round(statistics.median(readings), 2),
                                      "p95_ms": round(percentile(readings, .95), 2), "bytes": len(response.content),
                                      "sqlite_queries_per_request": sorted(set(query_counts)),
                                      "sqlite_connections_per_request": sorted(set(connect_counts)),
                                      "sqlite_query_ms": 0 if not any(query_counts) else "not measured"}, ensure_ascii=False))
                    if route == "/api/rotation/overview":
                        print(json.dumps({"route": route, "cold_ms": round(readings[0], 2),
                                          "hot_p50_ms": round(statistics.median(readings[1:]), 2)}, ensure_ascii=False))
            finally:
                sqlite3.connect = original_connect
            previous_id = manifest["snapshot_id"]
            next_id = previous_id[:-1] + ("0" if previous_id[-1] != "0" else "1")
            changed = {**manifest, "snapshot_id": next_id, "files": {}, "sha256": {}}
            for key, relative in manifest["files"].items():
                next_relative = f"releases/{next_id}/{Path(relative).name}"
                raw = (root / relative).read_bytes().replace(previous_id.encode(), next_id.encode())
                target = root / next_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                changed["files"][key] = next_relative
                changed["sha256"][key] = hashlib.sha256(raw).hexdigest()
            (root / "current_manifest.json").write_text(json.dumps(changed), encoding="utf-8")
            started = time.perf_counter()
            refreshed = client.get("/api/rotation/overview")
            print(json.dumps({"route": "/api/rotation/overview", "after_new_snapshot_first_ms":
                              round((time.perf_counter() - started) * 1000, 2),
                              "new_snapshot_status": refreshed.status_code,
                              "new_snapshot_id": refreshed.json().get("snapshot_id")}, ensure_ascii=False))
        for name, readings in segments.items():
            print(json.dumps({"segment": name, "n": len(readings), "p50_ms": round(statistics.median(readings), 2),
                              "p95_ms": round(percentile(readings, .95), 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
