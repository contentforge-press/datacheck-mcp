"""
dvq MCP Server

让 AI agent（Claude Desktop / Cursor / 任何支持 MCP 的客户端）能校验数据。

协议：Model Context Protocol（stdio transport）
零依赖，只用标准库。

工具：
  · validate_csv      —— 校验 CSV 文本，返回结构化问题清单
  · check_date        —— 检查日期是否真实存在
  · suggest_schema    —— 根据数据推断建议的字段类型
  · report_markdown   —— 生成可读报告
"""
from __future__ import annotations

import json
import os
import sys

# 导入共享内核
# 包内结构: server.py 和 core/validator.py 同级
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "core"))
from validator import to_dict, to_markdown, validate

# 销售引擎
try:
    from selling import (License, check_usage, resolve_license,
                         upsell_text)
    HAVE_SELLING = True
except ImportError:
    HAVE_SELLING = False


SERVER_NAME = "dvq"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


# ============================================================
# 工具定义
# ============================================================
TOOLS = [
    {
        "name": "validate_csv",
        "description": (
            "Validate CSV text and return a structured list of data problems: "
            "duplicate rows, duplicate keys, empty required fields, placeholder values "
            "like N/A, values that fail numeric parsing, and dates that parse but "
            "don't exist (e.g. 2026-02-30). Returns a 0-100 health score plus the "
            "exact rows that would be silently lost downstream."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv": {
                    "type": "string",
                    "description": "Raw CSV text, first line must be the header.",
                },
                "key_column": {
                    "type": "string",
                    "description": "Optional. Column that should be unique.",
                },
                "required_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Columns that must not be empty.",
                },
            },
            "required": ["csv"],
        },
    },
    {
        "name": "check_date",
        "description": (
            "Check whether a date string is a real calendar date. "
            "Catches values that most parsers accept but are impossible, "
            "like 2026-02-30 or 2026-13-45."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "The date string."}
            },
            "required": ["value"],
        },
    },
    {
        "name": "suggest_schema",
        "description": (
            "Infer column types from a CSV sample. Returns the likely type for each "
            "column (string, number, date, money, mixed) plus empty counts and "
            "uniqueness, which tells you which columns can be used as keys."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv": {"type": "string", "description": "Raw CSV text."}
            },
            "required": ["csv"],
        },
    },
    {
        "name": "report_markdown",
        "description": "Validate CSV and return a human-readable Markdown report.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv": {"type": "string", "description": "Raw CSV text."}
            },
            "required": ["csv"],
        },
    },
]


# ============================================================
# 工具实现
# ============================================================
def tool_validate_csv(args):
    from validator import validate as _v

    csv_text = args["csv"]
    row_count = csv_text.count("\n")

    # 销售引擎：许可 + 用量检查
    if HAVE_SELLING:
        lic = resolve_license()
        usage = check_usage(lic, "mcp", row_count)
        if not usage.allowed:
            return {
                "error": usage.reason,
                "message": usage.upsell_message,
                "upgrade": usage.checkout,
                "rows": row_count,
            }

    res = _v(
        csv_text,
        key_column=args.get("key_column"),
        required_columns=args.get("required_columns") or [],
    )
    d = to_dict(res)
    # 精简返回（MCP 响应不宜过大）
    return {
        "score": d["score"],
        "summary": d["summary"],
        "total_rows": d["total_rows"],
        "total_columns": d["total_columns"],
        "counts": d["counts"],
        "rows_at_risk": d["lossy_rows"][:50],
        "total_rows_at_risk": len(d["lossy_rows"]),
        "issues": d["issues"][:50],
        "total_issues": len(d["issues"]),
        "columns": [
            {
                "name": c["name"],
                "type": c["inferred_type"],
                "empty": c["empty_count"],
                "unique": c["unique_count"],
            }
            for c in d["columns"]
        ],
    }


def tool_check_date(args):
    from validator import check_date as _cd
    ok, reason = _cd(args["value"])
    return {
        "value": args["value"],
        "valid": ok,
        "reason": reason or "valid calendar date",
    }


def tool_suggest_schema(args):
    from validator import validate as _v
    res = _v(args["csv"])
    return {
        "columns": [
            {
                "name": c.name,
                "inferred_type": c.inferred_type,
                "empty_count": c.empty_count,
                "unique_count": c.unique_count,
                "total_rows": c.total_rows,
                "type_mismatch_rate": round(c.type_mismatch_rate, 3),
                "samples": c.samples,
            }
            for c in res.columns
        ]
    }


def tool_report_markdown(args):
    from validator import validate as _v
    return {"markdown": to_markdown(_v(args["csv"]))}


TOOL_IMPLS = {
    "validate_csv": tool_validate_csv,
    "check_date": tool_check_date,
    "suggest_schema": tool_suggest_schema,
    "report_markdown": tool_report_markdown,
}


# ============================================================
# JSON-RPC 处理
# ============================================================
def handle_request(req: dict) -> dict | None:
    """处理一个 JSON-RPC 请求"""
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    # 通知不需要响应
    is_notification = "id" not in req

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    if method == "tools/list":
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        if is_notification:
            return None
        name = params.get("name")
        args = params.get("arguments") or {}

        impl = TOOL_IMPLS.get(name)
        if not impl:
            return {
                "jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }

        try:
            out = impl(args)
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=2)}
                    ],
                    "isError": False,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {type(e).__name__}: {e}"}],
                    "isError": True,
                },
            }

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if is_notification:
        return None

    return {
        "jsonrpc": "2.0", "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio():
    """stdio 传输：一行一个 JSON-RPC 消息"""
    sys.stderr.write(f"[{SERVER_NAME}] MCP server started (v{SERVER_VERSION})\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def selftest():
    """自测：不走 stdio，直接测 handler"""
    print("=" * 70)
    print("MCP Server 自测")
    print("=" * 70)

    passed = failed = 0

    def t(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}  {detail}")

    # initialize
    r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {}})
    t("initialize 返回协议版本",
      r and r["result"]["protocolVersion"] == PROTOCOL_VERSION,
      str(r))
    t("initialize 有 serverInfo",
      r and r["result"]["serverInfo"]["name"] == SERVER_NAME)

    # tools/list
    r = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    t("tools/list 返回工具", r and len(r["result"]["tools"]) == 4,
      str(len(r["result"]["tools"]) if r else 0))

    # validate_csv
    csv_text = """id,email,amount,date
A-1,a@x.com,100,2026-01-01
A-1,b@x.com,abc,2026-02-30
A-2,,200,2026-03-01"""
    r = handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "validate_csv",
                   "arguments": {"csv": csv_text, "key_column": "id",
                                 "required_columns": ["email"]}},
    })
    t("validate_csv 成功", r and not r["result"]["isError"], str(r)[:100])
    if r and not r["result"]["isError"]:
        payload = json.loads(r["result"]["content"][0]["text"])
        t("返回健康分", "score" in payload, str(payload.get("score")))
        t("返回问题清单", len(payload["issues"]) > 0,
          str(len(payload["issues"])))
        t("检测到重复 key",
          any(i["type"] == "duplicate_key" for i in payload["issues"]),
          str([i["type"] for i in payload["issues"]]))

    # check_date
    r = handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "check_date", "arguments": {"value": "2026-02-30"}},
    })
    payload = json.loads(r["result"]["content"][0]["text"])
    t("check_date 识别 2月30日不存在", payload["valid"] is False, str(payload))

    r = handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "check_date", "arguments": {"value": "2026-02-28"}},
    })
    payload = json.loads(r["result"]["content"][0]["text"])
    t("check_date 通过正常日期", payload["valid"] is True, str(payload))

    # suggest_schema
    r = handle_request({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "suggest_schema", "arguments": {"csv": csv_text}},
    })
    payload = json.loads(r["result"]["content"][0]["text"])
    t("suggest_schema 返回列信息", len(payload["columns"]) == 4,
      str(len(payload["columns"])))

    # 未知工具
    r = handle_request({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    })
    t("未知工具返回错误", r and "error" in r, str(r))

    # 通知不响应
    r = handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    t("通知不产生响应", r is None, str(r))

    print("\n" + "=" * 70)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    serve_stdio()
