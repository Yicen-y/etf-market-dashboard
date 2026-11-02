"""Wind MCP connection settings and deliberately unverified index mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from scripts.config import INDEXES

DEFAULT_WIND_MCP_URL = "https://mcp.wind.com.cn/vserver_wind_tools/mcp/"


@dataclass(frozen=True)
class WindIndexMapping:
    local_code: str
    wind_code: str | None
    name: str
    index_type: str | None


@dataclass(frozen=True)
class WindConfig:
    endpoint: str
    authorization: str | None
    mappings: dict[str, WindIndexMapping]
    query_tool: str | None
    query_arguments: dict


def load_wind_config(environ: Mapping[str, str]) -> WindConfig:
    mappings = {
        code: WindIndexMapping(code, None, details["name"], None)
        for code, details in INDEXES.items()
    }
    return WindConfig(
        endpoint=environ.get("WIND_MCP_URL", DEFAULT_WIND_MCP_URL).strip(),
        authorization=environ.get("WIND_MCP_AUTH") or None,
        mappings=mappings,
        query_tool=environ.get("WIND_MCP_TOOL") or None,
        query_arguments={},
    )
