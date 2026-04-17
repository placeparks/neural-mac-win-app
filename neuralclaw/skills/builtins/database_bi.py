"""
Database BI Skill — Connect to databases, run natural-language queries,
generate charts, and produce business intelligence insights.

Supports: SQLite, PostgreSQL, MySQL, MongoDB, ClickHouse.
All connections stay local — no data leaves the machine unless the
database itself is remote.

Tools:
    db_connect          — Register a named database connection
    db_disconnect       — Remove a saved connection
    db_list_connections — Show all active connections
    db_list_tables      — Introspect schema: tables / collections
    db_describe_table   — Column names, types, sample rows
    db_query            — Execute raw SQL / MongoDB find
    db_natural_query    — Natural-language → SQL → execute → result
    db_chart            — Generate a chart (bar, line, pie, scatter, heatmap)
    db_explain_data     — Summarise / explain a query result in plain English
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import sqlite3
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from neuralclaw.skills.manifest import (
    Capability,
    SkillManifest,
    ToolDefinition,
    ToolParameter,
)

logger = logging.getLogger("neuralclaw.skills.database_bi")

# ---------------------------------------------------------------------------
# Connection registry (module-level singleton)
# ---------------------------------------------------------------------------

@dataclass
class _DBConnection:
    """A registered database connection."""
    name: str
    driver: str          # sqlite | postgres | mysql | mongodb | clickhouse
    dsn: str             # connection string / path
    schema: str = ""     # optional default schema
    read_only: bool = True
    _conn: Any = field(default=None, repr=False)
    _meta_cache: dict[str, Any] = field(default_factory=dict, repr=False)

_connections: dict[str, _DBConnection] = {}

# LLM provider reference — injected by gateway at init
_llm_provider: Any = None
_llm_provider_resolver: Callable[..., Awaitable[Any]] | None = None
_max_rows: int = 500
_max_chart_rows: int = 5000


def set_llm_provider(provider: Any) -> None:
    """Inject the LLM provider for natural-language query generation."""
    global _llm_provider
    _llm_provider = provider


def set_llm_provider_resolver(resolver: Callable[..., Awaitable[Any]] | None) -> None:
    """Inject a per-request LLM resolver for DB workspace routing."""
    global _llm_provider_resolver
    _llm_provider_resolver = resolver


def set_max_rows(n: int) -> None:
    global _max_rows
    _max_rows = max(1, n)


# ---------------------------------------------------------------------------
# Driver helpers — lazy imports keep startup fast
# ---------------------------------------------------------------------------

async def _get_driver_conn(conn: _DBConnection) -> Any:
    """Return or create the underlying database connection."""
    if conn._conn is not None:
        return conn._conn

    driver = conn.driver.lower()

    if driver == "sqlite":
        db_path = conn.dsn.replace("sqlite:///", "").replace("sqlite://", "")
        db_path = str(Path(db_path).expanduser().resolve())
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        if conn.read_only:
            c.execute("PRAGMA query_only = ON")
        conn._conn = c
        return c

    if driver in ("postgres", "postgresql"):
        import asyncpg  # type: ignore[import-untyped]
        c = await asyncpg.connect(conn.dsn)
        conn._conn = c
        return c

    if driver == "mysql":
        import aiomysql  # type: ignore[import-untyped]
        # Parse DSN like mysql://user:pass@host:port/db
        from urllib.parse import urlparse
        parsed = urlparse(conn.dsn)
        c = await aiomysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            db=parsed.path.lstrip("/") or "",
            autocommit=True,
        )
        conn._conn = c
        return c

    if driver == "mongodb":
        from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore[import-untyped]
        client = AsyncIOMotorClient(conn.dsn)
        # Extract database name from DSN path
        from urllib.parse import urlparse
        parsed = urlparse(conn.dsn)
        db_name = parsed.path.lstrip("/") or "test"
        conn._conn = client[db_name]
        return conn._conn

    if driver == "clickhouse":
        import aiohttp
        # ClickHouse HTTP interface — store base URL
        base = conn.dsn.rstrip("/")
        conn._conn = base
        return base

    raise ValueError(f"Unsupported database driver: {driver}")


async def _close_driver_conn(conn: _DBConnection) -> None:
    """Close the underlying connection."""
    if conn._conn is None:
        return
    driver = conn.driver.lower()
    try:
        if driver == "sqlite":
            conn._conn.close()
        elif driver in ("postgres", "postgresql"):
            await conn._conn.close()
        elif driver == "mysql":
            conn._conn.close()
        elif driver == "mongodb":
            conn._conn.client.close()
        # clickhouse HTTP has no persistent conn
    except Exception:
        pass
    conn._conn = None
    conn._meta_cache.clear()


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

async def _introspect_tables(conn: _DBConnection) -> list[dict[str, Any]]:
    """Return list of tables / collections with row counts."""
    cached = conn._meta_cache.get("tables")
    if cached is not None:
        return cached

    c = await _get_driver_conn(conn)
    driver = conn.driver.lower()
    tables: list[dict[str, Any]] = []

    if driver == "sqlite":
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for r in rows:
            name = r["name"]
            cnt = c.execute(f"SELECT COUNT(*) as cnt FROM [{name}]").fetchone()["cnt"]
            tables.append({"name": name, "rows": cnt})

    elif driver in ("postgres", "postgresql"):
        schema = conn.schema or "public"
        rows = await c.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = $1 ORDER BY table_name",
            schema,
        )
        for r in rows:
            name = r["table_name"]
            cnt_row = await c.fetchrow(f'SELECT COUNT(*) as cnt FROM "{schema}"."{name}"')
            tables.append({"name": name, "rows": cnt_row["cnt"] if cnt_row else 0})

    elif driver == "mysql":
        async with c.cursor(aiomysql.DictCursor) as cur:
            import aiomysql  # type: ignore[import-untyped]
            await cur.execute("SHOW TABLES")
            raw = await cur.fetchall()
            for r in raw:
                name = list(r.values())[0]
                await cur.execute(f"SELECT COUNT(*) as cnt FROM `{name}`")
                cnt_row = await cur.fetchone()
                tables.append({"name": name, "rows": cnt_row["cnt"] if cnt_row else 0})

    elif driver == "mongodb":
        db = c
        names = await db.list_collection_names()
        for name in sorted(names):
            cnt = await db[name].estimated_document_count()
            tables.append({"name": name, "rows": cnt, "type": "collection"})

    elif driver == "clickhouse":
        import aiohttp
        base = c
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                base, params={"query": "SHOW TABLES FORMAT JSON"}
            ) as resp:
                data = await resp.json()
                for r in data.get("data", []):
                    tables.append({"name": r.get("name", ""), "rows": 0})

    conn._meta_cache["tables"] = tables
    return tables


async def _introspect_columns(
    conn: _DBConnection, table: str
) -> list[dict[str, str]]:
    """Return column metadata for a specific table."""
    cache_key = f"cols_{table}"
    cached = conn._meta_cache.get(cache_key)
    if cached is not None:
        return cached

    c = await _get_driver_conn(conn)
    driver = conn.driver.lower()
    cols: list[dict[str, str]] = []

    if driver == "sqlite":
        rows = c.execute(f"PRAGMA table_info([{table}])").fetchall()
        for r in rows:
            cols.append({
                "name": r["name"],
                "type": r["type"] or "TEXT",
                "nullable": not bool(r["notnull"]),
                "primary_key": bool(r["pk"]),
            })

    elif driver in ("postgres", "postgresql"):
        schema = conn.schema or "public"
        rows = await c.fetch(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 "
            "ORDER BY ordinal_position",
            schema, table,
        )
        for r in rows:
            cols.append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
            })

    elif driver == "mysql":
        import aiomysql  # type: ignore[import-untyped]
        async with c.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"DESCRIBE `{table}`")
            raw = await cur.fetchall()
            for r in raw:
                cols.append({
                    "name": r["Field"],
                    "type": r["Type"],
                    "nullable": r["Null"] == "YES",
                    "primary_key": r["Key"] == "PRI",
                })

    elif driver == "mongodb":
        db = c
        sample = await db[table].find_one()
        if sample:
            for k, v in sample.items():
                cols.append({"name": k, "type": type(v).__name__})

    elif driver == "clickhouse":
        import aiohttp
        base = c
        async with aiohttp.ClientSession() as sess:
            q = f"DESCRIBE TABLE {table} FORMAT JSON"
            async with sess.get(base, params={"query": q}) as resp:
                data = await resp.json()
                for r in data.get("data", []):
                    cols.append({"name": r.get("name", ""), "type": r.get("type", "")})

    conn._meta_cache[cache_key] = cols
    return cols


async def _sample_rows(
    conn: _DBConnection, table: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Fetch a few sample rows for schema context."""
    c = await _get_driver_conn(conn)
    driver = conn.driver.lower()

    if driver == "sqlite":
        rows = c.execute(f"SELECT * FROM [{table}] LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    if driver in ("postgres", "postgresql"):
        schema = conn.schema or "public"
        rows = await c.fetch(f'SELECT * FROM "{schema}"."{table}" LIMIT $1', limit)
        return [dict(r) for r in rows]

    if driver == "mysql":
        import aiomysql  # type: ignore[import-untyped]
        async with c.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT * FROM `{table}` LIMIT %s", (limit,))
            return await cur.fetchall()

    if driver == "mongodb":
        db = c
        cursor = db[table].find().limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    if driver == "clickhouse":
        import aiohttp
        base = c
        async with aiohttp.ClientSession() as sess:
            q = f"SELECT * FROM {table} LIMIT {limit} FORMAT JSON"
            async with sess.get(base, params={"query": q}) as resp:
                data = await resp.json()
                return data.get("data", [])

    return []


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

async def _execute_query(
    conn: _DBConnection, sql: str, params: list | None = None
) -> dict[str, Any]:
    """Execute SQL and return {columns, rows, row_count}."""
    c = await _get_driver_conn(conn)
    driver = conn.driver.lower()

    if driver == "sqlite":
        cursor = c.execute(sql, params or [])
        desc = cursor.description
        if desc is None:
            return {"columns": [], "rows": [], "row_count": 0, "message": "Query executed (no result set)."}
        columns = [d[0] for d in desc]
        raw_rows = cursor.fetchmany(_max_rows)
        rows = [dict(zip(columns, r)) for r in raw_rows]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    if driver in ("postgres", "postgresql"):
        records = await c.fetch(sql, *(params or []))
        if not records:
            return {"columns": [], "rows": [], "row_count": 0}
        columns = list(records[0].keys())
        rows = [dict(r) for r in records[:_max_rows]]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    if driver == "mysql":
        import aiomysql  # type: ignore[import-untyped]
        async with c.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params or ())
            raw = await cur.fetchmany(_max_rows)
            if not raw:
                return {"columns": [], "rows": [], "row_count": 0}
            columns = list(raw[0].keys())
            return {"columns": columns, "rows": list(raw), "row_count": len(raw)}

    if driver == "mongodb":
        raise ValueError(
            "Use db_query with a MongoDB JSON filter, not raw SQL. "
            "Example: {\"collection\": \"users\", \"filter\": {\"age\": {\"$gt\": 25}}}"
        )

    if driver == "clickhouse":
        import aiohttp
        base = c
        q = sql if "FORMAT" in sql.upper() else f"{sql} FORMAT JSON"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(base, params={"query": q}) as resp:
                data = await resp.json()
                rows = data.get("data", [])[:_max_rows]
                columns = [m["name"] for m in data.get("meta", [])]
                return {"columns": columns, "rows": rows, "row_count": len(rows)}

    raise ValueError(f"Unsupported driver: {driver}")


async def _execute_mongo_query(
    conn: _DBConnection,
    collection: str,
    filter_doc: dict | None = None,
    projection: dict | None = None,
    sort: list | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Execute a MongoDB find query."""
    db = await _get_driver_conn(conn)
    cursor = db[collection].find(filter_doc or {}, projection)
    if sort:
        cursor = cursor.sort(sort)
    cursor = cursor.limit(min(limit, _max_rows))
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
    columns = list(results[0].keys()) if results else []
    return {"columns": columns, "rows": results, "row_count": len(results)}


# ---------------------------------------------------------------------------
# Natural-language query via LLM
# ---------------------------------------------------------------------------

async def _build_schema_context(conn: _DBConnection) -> str:
    """Build compact schema description for LLM context."""
    tables = await _introspect_tables(conn)
    parts = [f"Database: {conn.name} ({conn.driver})"]
    for t in tables:
        cols = await _introspect_columns(conn, t["name"])
        col_strs = [f"  {c['name']} ({c['type']})" for c in cols]
        parts.append(f"\nTable: {t['name']} ({t['rows']} rows)")
        parts.extend(col_strs)
    return "\n".join(parts)


async def _llm_generate_sql(
    question: str, schema_context: str, driver: str, llm_provider: Any
) -> str:
    """Ask the LLM to generate SQL from a natural-language question."""
    if not llm_provider:
        raise RuntimeError("No LLM provider configured for natural-language queries.")

    dialect_hints = {
        "sqlite": "SQLite (use LIMIT not TOP, || for concat, no ILIKE — use LIKE with LOWER())",
        "postgres": "PostgreSQL (ILIKE, date_trunc, generate_series, CTEs supported)",
        "postgresql": "PostgreSQL (ILIKE, date_trunc, generate_series, CTEs supported)",
        "mysql": "MySQL (backtick identifiers, LIMIT, DATE_FORMAT, GROUP_CONCAT)",
        "clickhouse": "ClickHouse (use FORMAT JSON at end, toDate/toMonth, arrayJoin)",
    }
    dialect = dialect_hints.get(driver.lower(), driver)

    messages = [
        {
            "role": "system",
            "content": textwrap.dedent(f"""\
                You are an expert SQL analyst. Given a database schema and a
                natural-language question, output ONLY the SQL query — no
                explanation, no markdown fences, no comments.

                SQL dialect: {dialect}
                Rules:
                - SELECT only; never INSERT/UPDATE/DELETE/DROP/ALTER/CREATE
                - Always LIMIT results to 500 rows max
                - Use aliases for clarity
                - If the question asks for a chart, include ORDER BY
                - For time series, order by date ascending
                - Return clean, executable SQL
            """),
        },
        {
            "role": "user",
            "content": f"Schema:\n{schema_context}\n\nQuestion: {question}",
        },
    ]
    resp = await llm_provider.complete(messages=messages, temperature=0.1, max_tokens=1024)
    sql = (resp.content or "").strip()
    # Strip markdown code fences if the model wraps them
    if sql.startswith("```"):
        lines = sql.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        sql = "\n".join(lines).strip()
    return sql


async def _llm_explain_results(
    question: str, sql: str, columns: list[str], rows: list[dict], driver: str, llm_provider: Any
) -> str:
    """Ask the LLM to explain query results in plain English."""
    if not llm_provider:
        return "No LLM provider configured for explanation."

    # Truncate rows for context window
    sample = rows[:50]
    messages = [
        {
            "role": "system",
            "content": (
                "You are a business intelligence analyst. Given a SQL query and its "
                "results, provide a clear, concise summary of the findings. Highlight "
                "key trends, outliers, and actionable insights. Use bullet points. "
                "If the data suggests further analysis, mention what to explore next."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question}\n"
                f"SQL ({driver}): {sql}\n"
                f"Columns: {columns}\n"
                f"Results ({len(rows)} rows, showing first {len(sample)}):\n"
                f"{json.dumps(sample, indent=2, default=str)}"
            ),
        },
    ]
    resp = await llm_provider.complete(messages=messages, temperature=0.3, max_tokens=2048)
    return resp.content or "Unable to generate explanation."


async def _resolve_llm_runtime(
    provider: str = "",
    model: str = "",
    base_url: str = "",
    allow_fallback: bool | None = None,
) -> Any:
    if _llm_provider_resolver:
        candidate = await _llm_provider_resolver(
            provider=provider,
            model=model,
            base_url=base_url,
            allow_fallback=allow_fallback,
        )
        if candidate is not None:
            return candidate
    if _llm_provider is not None:
        return _llm_provider
    raise RuntimeError("No LLM provider configured for natural-language queries.")


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def _generate_chart(
    chart_type: str,
    columns: list[str],
    rows: list[dict],
    title: str = "",
    x_col: str = "",
    y_col: str = "",
    group_col: str = "",
) -> dict[str, Any]:
    """Generate a chart and return base64 PNG + metadata."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        return {"error": "matplotlib is required for charting. Install: pip install matplotlib"}

    if not rows:
        return {"error": "No data to chart."}

    # Auto-detect columns if not specified
    if not x_col:
        x_col = columns[0] if columns else ""
    if not y_col and len(columns) > 1:
        # Pick first numeric column
        for col in columns[1:]:
            val = rows[0].get(col)
            if isinstance(val, (int, float)):
                y_col = col
                break
        if not y_col:
            y_col = columns[1] if len(columns) > 1 else columns[0]

    x_data = [r.get(x_col, "") for r in rows[:_max_chart_rows]]
    y_data = []
    for r in rows[:_max_chart_rows]:
        v = r.get(y_col, 0)
        try:
            y_data.append(float(v) if v is not None else 0)
        except (ValueError, TypeError):
            y_data.append(0)

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    ax.tick_params(colors="#c9d1d9")
    ax.xaxis.label.set_color("#c9d1d9")
    ax.yaxis.label.set_color("#c9d1d9")
    ax.title.set_color("#c9d1d9")
    for spine in ax.spines.values():
        spine.set_color("#30363d")

    chart_type = chart_type.lower()
    if chart_type == "bar":
        bars = ax.bar(range(len(x_data)), y_data, color="#58a6ff", edgecolor="#1f6feb")
        ax.set_xticks(range(len(x_data)))
        ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)
    elif chart_type == "line":
        ax.plot(range(len(x_data)), y_data, color="#58a6ff", linewidth=2, marker="o", markersize=4)
        ax.fill_between(range(len(x_data)), y_data, alpha=0.1, color="#58a6ff")
        ax.set_xticks(range(len(x_data)))
        ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)
    elif chart_type == "pie":
        colors = plt.cm.Set2.colors  # type: ignore[attr-defined]
        wedges, texts, autotexts = ax.pie(
            y_data, labels=x_data, autopct="%1.1f%%",
            colors=colors[:len(x_data)],
            textprops={"color": "#c9d1d9", "fontsize": 9},
        )
    elif chart_type == "scatter":
        ax.scatter(range(len(x_data)), y_data, color="#58a6ff", alpha=0.7, edgecolors="#1f6feb")
        ax.set_xticks(range(len(x_data)))
        ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)
    elif chart_type == "heatmap":
        try:
            import numpy as np
            # Build a matrix from the data
            if group_col and group_col in columns:
                groups = sorted(set(r.get(group_col, "") for r in rows))
                x_labels = sorted(set(r.get(x_col, "") for r in rows))
                matrix = np.zeros((len(groups), len(x_labels)))
                g_idx = {g: i for i, g in enumerate(groups)}
                x_idx = {x: i for i, x in enumerate(x_labels)}
                for r in rows:
                    gi = g_idx.get(r.get(group_col, ""))
                    xi = x_idx.get(r.get(x_col, ""))
                    if gi is not None and xi is not None:
                        try:
                            matrix[gi][xi] = float(r.get(y_col, 0) or 0)
                        except (ValueError, TypeError):
                            pass
                im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
                ax.set_xticks(range(len(x_labels)))
                ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)
                ax.set_yticks(range(len(groups)))
                ax.set_yticklabels(groups, fontsize=8)
                fig.colorbar(im, ax=ax)
            else:
                # Fallback to bar chart
                ax.bar(range(len(x_data)), y_data, color="#58a6ff")
                ax.set_xticks(range(len(x_data)))
                ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)
        except ImportError:
            ax.bar(range(len(x_data)), y_data, color="#58a6ff")
            ax.set_xticks(range(len(x_data)))
            ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)
    else:
        ax.bar(range(len(x_data)), y_data, color="#58a6ff")
        ax.set_xticks(range(len(x_data)))
        ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=8)

    ax.set_xlabel(x_col)
    if chart_type != "pie":
        ax.set_ylabel(y_col)
    ax.set_title(title or f"{y_col} by {x_col}", fontsize=14, fontweight="bold")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")

    return {
        "chart_type": chart_type,
        "x_column": x_col,
        "y_column": y_col,
        "data_points": len(x_data),
        "image_base64": b64,
        "title": title or f"{y_col} by {x_col}",
    }


# ---------------------------------------------------------------------------
# Public tool handlers
# ---------------------------------------------------------------------------

async def db_connect(
    name: str,
    driver: str,
    dsn: str,
    schema: str = "",
    read_only: bool = True,
    **kwargs: Any,
) -> str:
    """Register a named database connection.

    Args:
        name: Friendly name for this connection (e.g. "sales_db").
        driver: One of: sqlite, postgres, mysql, mongodb, clickhouse.
        dsn: Connection string.
             SQLite: path to .db file (e.g. ~/data/sales.db)
             PostgreSQL: postgresql://user:pass@host:5432/dbname
             MySQL: mysql://user:pass@host:3306/dbname
             MongoDB: mongodb://host:27017/dbname
             ClickHouse: http://host:8123
        schema: Default schema (PostgreSQL only, defaults to "public").
        read_only: If true, prevents write queries (default: true).
    """
    driver = driver.lower().strip()
    valid_drivers = {"sqlite", "postgres", "postgresql", "mysql", "mongodb", "clickhouse"}
    if driver not in valid_drivers:
        return f"Error: Unsupported driver '{driver}'. Use one of: {', '.join(sorted(valid_drivers))}"

    # Close existing connection with same name
    if name in _connections:
        await _close_driver_conn(_connections[name])

    conn = _DBConnection(
        name=name, driver=driver, dsn=dsn,
        schema=schema, read_only=read_only,
    )

    # Test connectivity
    try:
        await _get_driver_conn(conn)
        tables = await _introspect_tables(conn)
        _connections[name] = conn
        return (
            f"Connected to '{name}' ({driver}). "
            f"Found {len(tables)} tables/collections: "
            f"{', '.join(t['name'] for t in tables[:20])}"
            f"{'...' if len(tables) > 20 else ''}"
        )
    except Exception as e:
        await _close_driver_conn(conn)
        return f"Connection failed: {e}"


async def db_disconnect(name: str, **kwargs: Any) -> str:
    """Remove a saved database connection."""
    if name not in _connections:
        return f"No connection named '{name}'. Active: {', '.join(_connections.keys()) or '(none)'}"
    await _close_driver_conn(_connections[name])
    del _connections[name]
    return f"Disconnected from '{name}'."


async def db_list_connections(**kwargs: Any) -> str:
    """Show all active database connections."""
    if not _connections:
        return "No active database connections. Use db_connect to add one."
    lines = []
    for name, conn in _connections.items():
        tables = conn._meta_cache.get("tables", [])
        lines.append(
            f"- {name}: {conn.driver} | {len(tables)} tables | "
            f"read_only={conn.read_only}"
        )
    return "Active connections:\n" + "\n".join(lines)


async def db_list_tables(connection: str, **kwargs: Any) -> str:
    """List all tables / collections in a connected database.

    Args:
        connection: Name of the database connection.
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'. Active: {', '.join(_connections.keys()) or '(none)'}"

    tables = await _introspect_tables(conn)
    if not tables:
        return f"No tables found in '{connection}'."

    lines = [f"Tables in '{connection}' ({conn.driver}):"]
    for t in tables:
        ttype = t.get("type", "table")
        lines.append(f"  {t['name']}: {t['rows']:,} rows ({ttype})")
    return "\n".join(lines)


async def db_describe_table(
    connection: str, table: str, **kwargs: Any
) -> str:
    """Show column details and sample rows for a table.

    Args:
        connection: Name of the database connection.
        table: Table or collection name.
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'."

    cols = await _introspect_columns(conn, table)
    if not cols:
        return f"Table '{table}' not found or has no columns."

    sample = await _sample_rows(conn, table, limit=3)

    lines = [f"Table: {table}", "Columns:"]
    for c in cols:
        pk = " [PK]" if c.get("primary_key") else ""
        null = " (nullable)" if c.get("nullable") else ""
        lines.append(f"  {c['name']}: {c['type']}{pk}{null}")

    if sample:
        lines.append(f"\nSample rows ({len(sample)}):")
        lines.append(json.dumps(sample, indent=2, default=str))

    return "\n".join(lines)


async def db_query(
    connection: str, query: str, **kwargs: Any
) -> str:
    """Execute a raw SQL query (or MongoDB find) and return results.

    Args:
        connection: Name of the database connection.
        query: SQL query string. For MongoDB, pass a JSON object with
               keys: collection, filter, projection, sort, limit.
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'."

    # Safety: block writes on read-only connections
    if conn.read_only:
        q_upper = query.strip().upper()
        write_keywords = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "REPLACE")
        if any(q_upper.startswith(kw) for kw in write_keywords):
            return "Error: This connection is read-only. Write operations are blocked."

    try:
        if conn.driver.lower() == "mongodb":
            params = json.loads(query)
            result = await _execute_mongo_query(
                conn,
                collection=params["collection"],
                filter_doc=params.get("filter"),
                projection=params.get("projection"),
                sort=params.get("sort"),
                limit=params.get("limit", 100),
            )
        else:
            result = await _execute_query(conn, query)

        if not result["rows"]:
            return result.get("message", "Query returned no results.")

        # Format as compact table
        output = f"Columns: {result['columns']}\nRows: {result['row_count']}\n"
        output += json.dumps(result["rows"][:100], indent=2, default=str)
        if result["row_count"] > 100:
            output += f"\n... and {result['row_count'] - 100} more rows"
        return output
    except Exception as e:
        return f"Query error: {e}"


async def db_natural_query(
    connection: str, question: str, **kwargs: Any
) -> str:
    """Ask a natural-language question about your database.

    The LLM generates SQL from your question, executes it, and returns
    the results with an explanation.

    Args:
        connection: Name of the database connection.
        question: Natural-language question (e.g. "What were total sales last month?").
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'."

    if conn.driver.lower() == "mongodb":
        return (
            "Natural-language queries are not yet supported for MongoDB. "
            "Use db_query with a JSON filter instead."
        )

    try:
        llm_provider = await _resolve_llm_runtime(
            provider=str(kwargs.get("provider", "") or ""),
            model=str(kwargs.get("model", "") or ""),
            base_url=str(kwargs.get("base_url", "") or ""),
            allow_fallback=kwargs.get("allow_fallback"),
        )
        schema_ctx = await _build_schema_context(conn)
        sql = await _llm_generate_sql(question, schema_ctx, conn.driver, llm_provider)

        # Safety check
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            return f"Safety block: LLM generated a non-SELECT query:\n{sql}"

        result = await _execute_query(conn, sql)

        explanation = await _llm_explain_results(
            question, sql, result["columns"], result["rows"], conn.driver, llm_provider
        )

        output_parts = [
            f"Question: {question}",
            f"Generated SQL:\n```sql\n{sql}\n```",
            f"Results: {result['row_count']} rows",
        ]
        if result["rows"]:
            output_parts.append(json.dumps(result["rows"][:50], indent=2, default=str))
        output_parts.append(f"\nAnalysis:\n{explanation}")

        return "\n\n".join(output_parts)
    except Exception as e:
        return f"Natural query failed: {e}"


async def db_chart(
    connection: str,
    query: str,
    chart_type: str = "bar",
    title: str = "",
    x_column: str = "",
    y_column: str = "",
    group_column: str = "",
    **kwargs: Any,
) -> str:
    """Execute a query and generate a chart from the results.

    Args:
        connection: Name of the database connection.
        query: SQL query (or natural-language question if it doesn't start with SELECT/WITH).
        chart_type: One of: bar, line, pie, scatter, heatmap.
        title: Chart title.
        x_column: Column for X axis (auto-detected if empty).
        y_column: Column for Y axis (auto-detected if empty).
        group_column: Column for grouping (heatmap Y axis).
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'."

    try:
        llm_provider = await _resolve_llm_runtime(
            provider=str(kwargs.get("provider", "") or ""),
            model=str(kwargs.get("model", "") or ""),
            base_url=str(kwargs.get("base_url", "") or ""),
            allow_fallback=kwargs.get("allow_fallback"),
        )
        q = query.strip()
        sql = q
        # If it doesn't look like SQL, treat as natural language
        if not q.upper().startswith(("SELECT", "WITH")):
            if conn.driver.lower() == "mongodb":
                return "Chart generation requires SQL. MongoDB is not supported for charting."
            schema_ctx = await _build_schema_context(conn)
            sql = await _llm_generate_sql(q, schema_ctx, conn.driver, llm_provider)

        result = await _execute_query(conn, sql)
        if not result["rows"]:
            return "Query returned no data to chart."

        chart = _generate_chart(
            chart_type=chart_type,
            columns=result["columns"],
            rows=result["rows"],
            title=title,
            x_col=x_column,
            y_col=y_column,
            group_col=group_column,
        )

        if "error" in chart:
            return chart["error"]

        return (
            f"Chart generated: {chart['title']}\n"
            f"Type: {chart['chart_type']} | Data points: {chart['data_points']}\n"
            f"X: {chart['x_column']} | Y: {chart['y_column']}\n"
            f"SQL: {sql}\n"
            f"[Chart image: base64 PNG, {len(chart['image_base64'])} chars]"
        )
    except Exception as e:
        return f"Chart generation failed: {e}"


async def db_explain_data(
    connection: str, question: str, **kwargs: Any
) -> str:
    """Run a natural-language query and return only the business explanation.

    Like db_natural_query but focused on the analysis, not the raw data.

    Args:
        connection: Name of the database connection.
        question: Business question (e.g. "Why did revenue drop in March?").
    """
    conn = _connections.get(connection)
    if not conn:
        return f"No connection named '{connection}'."

    if conn.driver.lower() == "mongodb":
        return "Natural-language explain is not supported for MongoDB."

    try:
        llm_provider = await _resolve_llm_runtime(
            provider=str(kwargs.get("provider", "") or ""),
            model=str(kwargs.get("model", "") or ""),
            base_url=str(kwargs.get("base_url", "") or ""),
            allow_fallback=kwargs.get("allow_fallback"),
        )
        schema_ctx = await _build_schema_context(conn)
        sql = await _llm_generate_sql(question, schema_ctx, conn.driver, llm_provider)

        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            return f"Safety block: LLM generated a non-SELECT query."

        result = await _execute_query(conn, sql)
        explanation = await _llm_explain_results(
            question, sql, result["columns"], result["rows"], conn.driver, llm_provider
        )
        return explanation
    except Exception as e:
        return f"Explain failed: {e}"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="database_bi",
        description=(
            "Connect to databases (SQLite, PostgreSQL, MySQL, MongoDB, ClickHouse), "
            "run natural-language queries, generate charts, and produce business "
            "intelligence insights — all locally."
        ),
        version="1.0.0",
        author="neuralclaw",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="db_connect",
                description=(
                    "Register a named database connection. Supports SQLite, "
                    "PostgreSQL, MySQL, MongoDB, and ClickHouse."
                ),
                parameters=[
                    ToolParameter(name="name", type="string", description="Friendly name for this connection (e.g. 'sales_db')"),
                    ToolParameter(name="driver", type="string", description="Database driver: sqlite, postgres, mysql, mongodb, or clickhouse"),
                    ToolParameter(name="dsn", type="string", description="Connection string or file path. SQLite: ~/data/sales.db, PostgreSQL: postgresql://user:pass@host:5432/db, MySQL: mysql://user:pass@host/db, MongoDB: mongodb://host:27017/db, ClickHouse: http://host:8123"),
                    ToolParameter(name="schema", type="string", description="Default schema (PostgreSQL only, defaults to 'public')", required=False),
                    ToolParameter(name="read_only", type="boolean", description="Block write operations (default: true)", required=False),
                ],
                handler=db_connect,
            ),
            ToolDefinition(
                name="db_disconnect",
                description="Remove a saved database connection.",
                parameters=[
                    ToolParameter(name="name", type="string", description="Connection name to disconnect"),
                ],
                handler=db_disconnect,
            ),
            ToolDefinition(
                name="db_list_connections",
                description="Show all active database connections with status.",
                parameters=[],
                handler=db_list_connections,
            ),
            ToolDefinition(
                name="db_list_tables",
                description="List all tables or collections in a connected database with row counts.",
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                ],
                handler=db_list_tables,
            ),
            ToolDefinition(
                name="db_describe_table",
                description="Show column names, types, and sample rows for a specific table.",
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                    ToolParameter(name="table", type="string", description="Table or collection name"),
                ],
                handler=db_describe_table,
            ),
            ToolDefinition(
                name="db_query",
                description=(
                    "Execute a raw SQL query and return results. For MongoDB, pass "
                    "a JSON object with keys: collection, filter, projection, sort, limit."
                ),
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                    ToolParameter(name="query", type="string", description="SQL query or MongoDB JSON filter"),
                ],
                handler=db_query,
            ),
            ToolDefinition(
                name="db_natural_query",
                description=(
                    "Ask a natural-language question about your database. "
                    "Automatically generates SQL, executes it, and explains the results. "
                    "Example: 'What were total sales by region last quarter?'"
                ),
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                    ToolParameter(name="question", type="string", description="Natural-language question about your data"),
                ],
                handler=db_natural_query,
            ),
            ToolDefinition(
                name="db_chart",
                description=(
                    "Execute a query (SQL or natural language) and generate a chart. "
                    "Supports bar, line, pie, scatter, and heatmap charts."
                ),
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                    ToolParameter(name="query", type="string", description="SQL query or natural-language question"),
                    ToolParameter(name="chart_type", type="string", description="Chart type: bar, line, pie, scatter, or heatmap", required=False),
                    ToolParameter(name="title", type="string", description="Chart title", required=False),
                    ToolParameter(name="x_column", type="string", description="Column for X axis (auto-detected if empty)", required=False),
                    ToolParameter(name="y_column", type="string", description="Column for Y axis (auto-detected if empty)", required=False),
                    ToolParameter(name="group_column", type="string", description="Column for grouping / heatmap Y axis", required=False),
                ],
                handler=db_chart,
            ),
            ToolDefinition(
                name="db_explain_data",
                description=(
                    "Run a natural-language query and return only the business "
                    "analysis — key trends, outliers, and actionable insights."
                ),
                parameters=[
                    ToolParameter(name="connection", type="string", description="Name of the database connection"),
                    ToolParameter(name="question", type="string", description="Business question about your data"),
                ],
                handler=db_explain_data,
            ),
        ],
    )
