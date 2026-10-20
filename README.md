# dvq MCP Server

Give your AI agent the ability to check whether data is actually correct.

## Why an agent needs this

An agent that can query a database is useful. An agent that can tell you *the data it just queried is wrong* is trustworthy.

This MCP server exposes data validation as tools:

| Tool | What it does |
|---|---|
| `validate_csv` | Returns a 0-100 health score plus every problem row with the exact reason |
| `check_date` | Catches `2026-02-30` — parses fine, does not exist |
| `suggest_schema` | Infers column types and flags which columns can be used as keys |
| `report_markdown` | Generates a human-readable report |

## Install

```bash
npm install -g @dvq/mcp-server
```

Add to your MCP client config:

```json
{
  "mcpServers": {
    "dvq": {
      "command": "npx",
      "args": ["-y", "@dvq/mcp-server"]
    }
  }
}
```

## Example

Ask your agent: *"Check this CSV before you import it"*

The agent calls `validate_csv` and gets back:

```json
{
  "score": 48,
  "summary": "Serious problems. Do not load this as-is.",
  "counts": { "high": 4, "mid": 1, "low": 1 },
  "rows_at_risk": [4, 5, 8],
  "issues": [
    {
      "type": "duplicate_key",
      "row": 4,
      "column": "order_id",
      "reason": "key repeats (first seen at row 3)",
      "fix": "a join on this column will produce duplicate output rows"
    }
  ]
}
```

Now the agent can tell you *"don't import this yet — row 4 duplicates row 3's key"* instead of silently building on broken data.

## Pro

Free: single-table validation.
Pro: `validate_cross_table` and `watch_dataset` (get notified when data breaks).
https://checkout.dodopayments.com/buy/pdt_0Nq62Ecr9PnrPukjAEhaM?ref=mcp-server

## License

MIT

---

## All DataCheck tools

| Tool | Install | Docs |
|---|---|---|
| **n8n node** | `npm install n8n-nodes-datacheck` | [docs](https://contentforge-press.github.io/n8n-nodes-datacheck/) |
| **MCP server** | `npm install -g datacheck-mcp` | [docs](https://contentforge-press.github.io/datacheck-mcp/) |
| **Python CLI** | [git clone](https://github.com/contentforge-press/dvq) | [docs](https://contentforge-press.github.io/dvq/) |
| **Core library** | [git clone](https://github.com/contentforge-press/datacheck-core) | [docs](https://contentforge-press.github.io/datacheck-core/) |
| **Browser check** | no install | [try it](https://contentforge-press.github.io/data-health-check/) |

Product home: [datacheck.pixharvest.com](https://datacheck.pixharvest.com)
