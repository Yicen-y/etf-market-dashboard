"""Discover Wind MCP tools and produce read-only historical-point reports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from scripts.config import DATABASE_PATH, INDEXES
from scripts.wind_config import load_wind_config
from scripts.wind_mcp_client import WindMcpClient, WindMcpError
from scripts.wind_credentials import get_authorization
from scripts.wind_validator import compare_index_rows, load_local_index_rows, normalize_wind_rows


def write_report(report: dict, output_dir: Path, output_format: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"wind-validation-{stamp}.{output_format}"
    if output_format == "json":
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        fields = ["indexCode", "tradeDate", "status", "localValue", "windValue", "absoluteDelta", "relativeDelta"]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(report.get("results", []))
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only compare local index point histories with Wind Alice MCP.")
    parser.add_argument("--list-tools", action="store_true", help="discover and print authorized tool schemas")
    parser.add_argument("--tool", help="tool name discovered from --list-tools")
    parser.add_argument("--arguments-json", help="explicit JSON object passed to the selected Wind tool")
    parser.add_argument("--codes", nargs="+", help="local index codes to compare")
    parser.add_argument("--start", help="first trade date YYYYMMDD")
    parser.add_argument("--end", help="last trade date YYYYMMDD")
    parser.add_argument("--date-field", help="explicit date field in tool result rows")
    parser.add_argument("--close-field", help="explicit close field in tool result rows")
    parser.add_argument("--rows-field", default="rows", help="array field in tool result JSON (default: rows)")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/wind"))
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--wind-codes-json", help="explicit JSON mapping from local code to Wind code")
    return parser


def _payload_from_tool_result(result: dict) -> dict:
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                value = json.loads(item.get("text", ""))
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    raise ValueError("Tool response has no JSON object content; inspect its schema/output before configuring parsing")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_wind_config(os.environ)
    authorization = config.authorization or get_authorization()
    if not authorization:
        print("Wind MCP 需要授权（WIND_MCP_AUTH）。请运行 python -m scripts.wind_credentials set。", file=sys.stdout)
        return 2
    if not args.list_tools:
        missing = [name for name, value in (("--tool", args.tool), ("--arguments-json", args.arguments_json), ("--codes", args.codes), ("--start", args.start), ("--end", args.end), ("--date-field", args.date_field), ("--close-field", args.close_field), ("--wind-codes-json", args.wind_codes_json)) if not value]
        if missing:
            print("查询配置不完整；需显式指定 " + ", ".join(missing) + "。先运行 --list-tools 获取账户实际 schema。")
            return 2
    try:
        with WindMcpClient(config.endpoint, authorization) as client:
            client.initialize()
            tools = client.list_tools()
            if args.list_tools:
                print(json.dumps(tools, ensure_ascii=False, indent=2))
                return 0
            tool = next((item for item in tools if item.get("name") == args.tool), None)
            if not tool:
                print(f"指定工具未出现在当前账户的 tools/list 中：{args.tool}")
                return 2
            arguments = json.loads(args.arguments_json)
            wind_codes = json.loads(args.wind_codes_json)
            if not isinstance(arguments, dict) or not isinstance(wind_codes, dict):
                raise ValueError("arguments-json and wind-codes-json must be JSON objects")
            local_codes = args.codes
            if set(local_codes) - set(INDEXES):
                raise ValueError("Unknown local index code requested")
            if set(local_codes) - set(wind_codes):
                raise ValueError("Wind mapping missing for one or more requested local codes")
            combined = []
            local = load_local_index_rows(args.database, args.start, args.end)
            for code in local_codes:
                from scripts.wind_config import WindIndexMapping
                mapping = WindIndexMapping(code, str(wind_codes[code]), INDEXES[code]["name"], None)
                rendered_arguments = json.loads(args.arguments_json.replace("${wind_code}", str(wind_codes[code])).replace("${local_code}", code).replace("${start}", args.start).replace("${end}", args.end))
                result = client.call_tool(args.tool, rendered_arguments)
                payload = _payload_from_tool_result(result)
                wind_rows = normalize_wind_rows(payload, mapping, date_field=args.date_field, close_field=args.close_field, rows_field=args.rows_field)
                wind_rows = [row for row in wind_rows if args.start <= row["tradeDate"] <= args.end]
                local_selected = {key: value for key, value in local.items() if key[0] == code}
                combined.extend(compare_index_rows(local_selected, wind_rows))
            report = {
                "createdAt": datetime.now(timezone.utc).isoformat(), "endpointHost": urlparse(config.endpoint).hostname,
                "tool": args.tool, "startDate": args.start, "endDate": args.end,
                "codes": local_codes, "results": combined,
            }
            path = write_report(report, args.output_dir, args.format)
            print(f"校验报告已生成：{path}; rows={len(combined)}; mismatches={sum(r['status'] != 'MATCH' for r in combined)}")
            return 1 if any(row["status"] != "MATCH" for row in combined) else 0
    except (WindMcpError, ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"Wind 校验失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
