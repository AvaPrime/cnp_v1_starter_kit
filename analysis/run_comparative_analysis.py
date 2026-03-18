from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psutil


ROOT_FILES = Path(r"c:\Projects\files")
ROOT_PROD = Path(r"c:\Projects\cnp_v1_starter_kit")
OUT_DIR = ROOT_FILES / "analysis" / "out"


@dataclass(frozen=True)
class SystemUnderTest:
    system_id: str
    label: str
    base_url: str
    start_cmd: list[str]
    cwd: Path
    readiness_url: str


FILES_GATEWAY = SystemUnderTest(
    system_id="files",
    label="c:\\Projects\\files",
    base_url="http://127.0.0.1:5000",
    readiness_url="http://127.0.0.1:5000/health",
    start_cmd=[sys.executable, str(ROOT_FILES / "gateway.py")],
    cwd=ROOT_FILES,
)

PROD_GATEWAY = SystemUnderTest(
    system_id="prod",
    label="c:\\Projects\\cnp_v1_starter_kit",
    base_url="http://127.0.0.1:8080",
    readiness_url="http://127.0.0.1:8080/api/health",
    start_cmd=[sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"],
    cwd=ROOT_PROD / "gateway",
)


def ensure_out_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def run(cmd: list[str], cwd: Path | None = None, timeout_s: int | None = None) -> tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_s,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return p.returncode, p.stdout


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def glob_text_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        out.extend(root.glob(pat))
    return sorted({p for p in out if p.is_file()})


def extract_python_requirements_files(root: Path) -> list[str]:
    req = root / "gateway" / "requirements.txt"
    if req.exists():
        lines = [ln.strip() for ln in read_text(req).splitlines() if ln.strip() and not ln.strip().startswith("#")]
        return lines
    return []


def extract_gateway_endpoints_files_gateway(path: Path) -> list[dict[str, str]]:
    text = read_text(path)
    endpoints: list[dict[str, str]] = []
    for m in re.finditer(r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"', text):
        endpoints.append({"method": m.group(1).upper(), "path": m.group(2), "source": str(path)})
    return endpoints


def extract_gateway_endpoints_prod(root_gateway_app: Path) -> list[dict[str, str]]:
    routes = root_gateway_app / "app" / "api" / "routes.py"
    if not routes.exists():
        return []
    text = read_text(routes)
    endpoints: list[dict[str, str]] = []
    for m in re.finditer(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"', text):
        endpoints.append({"method": m.group(1).upper(), "path": "/api" + m.group(2), "source": str(routes)})
    return endpoints


def parse_sqlite_schema_node_registry(sql_text: str) -> dict[str, Any]:
    tables: dict[str, list[str]] = {}
    views: dict[str, str] = {}
    triggers: list[str] = []

    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)\s*\((.*?)\);\s*", sql_text, re.S):
        name = m.group(1)
        cols_block = m.group(2)
        cols = []
        for ln in cols_block.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("--"):
                continue
            ln = ln.rstrip(",")
            col_name = ln.split()[0]
            if col_name.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
                continue
            cols.append(col_name)
        tables[name] = cols

    for m in re.finditer(r"CREATE VIEW IF NOT EXISTS\s+([a-zA-Z0-9_]+)\s+AS\s+(.*?);", sql_text, re.S):
        views[m.group(1)] = m.group(2).strip()

    for m in re.finditer(r"CREATE TRIGGER IF NOT EXISTS\s+([a-zA-Z0-9_]+)\s+", sql_text):
        triggers.append(m.group(1))

    return {"tables": tables, "views": views, "triggers": triggers}


def parse_sqlite_schema_from_python_literal(py_text: str) -> dict[str, Any]:
    m = re.search(r'SCHEMA_SQL\s*=\s*"""\s*(.*?)\s*"""', py_text, re.S)
    if not m:
        return {"tables": {}, "views": {}, "triggers": []}
    return parse_sqlite_schema_node_registry(m.group(1))


def extract_mqtt_topics_prod(mqtt_client_text: str) -> dict[str, Any]:
    topics: set[str] = set()
    for m in re.finditer(r'"(cnp/v1/[^"]+)"', mqtt_client_text):
        topics.add(m.group(1))
    for m in re.finditer(r"f\"(cnp/v1/[^\\\"]+)\"", mqtt_client_text):
        topics.add(m.group(1))
    return {"topics": sorted(topics)}


def extract_mqtt_config_prod() -> dict[str, Any]:
    conf = ROOT_PROD / "examples" / "mosquitto.conf"
    if not conf.exists():
        return {}
    return {"mosquitto.conf": read_text(conf).strip()}


def extract_integrations_files_gateway(text: str) -> list[str]:
    hits: list[str] = []
    if "MEMORY BRIDGE HOOK" in text:
        hits.append("Memory Cortex bridge hook (placeholder)")
    if "VALID_TOKENS" in text:
        hits.append("HTTP bearer token via X-CNP-Token (static allow-list)")
    return hits


def extract_integrations_prod_gateway() -> list[str]:
    hits: list[str] = []
    conf = read_text(ROOT_PROD / "examples" / "mosquitto.conf")
    if "allow_anonymous true" in conf:
        hits.append("Mosquitto allow_anonymous=true (dev convenience)")
    return hits


def extract_openapi_from_files_gateway() -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("cnp_files_gateway", str(ROOT_FILES / "gateway.py"))
    if not spec or not spec.loader:
        raise RuntimeError("Failed to load files gateway module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cnp_files_gateway"] = mod
    spec.loader.exec_module(mod)
    app = getattr(mod, "app")
    return app.openapi()


def extract_openapi_from_prod_gateway() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT_PROD / "gateway"))
    from app.main import app  # type: ignore

    return app.openapi()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * p
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return values_sorted[f]
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return d0 + d1


async def http_load(
    base_url: str,
    path: str,
    concurrency: int,
    duration_s: float,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    import httpx

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    latencies_ms: list[float] = []
    status_codes: list[int] = []
    errors = 0
    error_kinds: dict[str, int] = {}
    start = time.perf_counter()
    deadline = start + duration_s

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal errors
        while True:
            now = time.perf_counter()
            if now >= deadline:
                return
            t0 = time.perf_counter()
            try:
                r = await client.get(base_url + path)
                dt = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(dt)
                status_codes.append(r.status_code)
            except Exception:
                errors += 1
                k = type(sys.exc_info()[1]).__name__ if sys.exc_info()[1] else "Exception"
                error_kinds[k] = error_kinds.get(k, 0) + 1

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        tasks = [asyncio.create_task(worker(client)) for _ in range(concurrency)]
        await asyncio.gather(*tasks)

    total_s = max(1e-9, time.perf_counter() - start)
    total = len(latencies_ms) + errors
    ok = sum(1 for s in status_codes if 200 <= s < 400)
    err_rate = (total - ok) / total if total else 0.0
    rps = total / total_s if total_s else 0.0

    return {
        "path": path,
        "concurrency": concurrency,
        "duration_s": duration_s,
        "requests_total": total,
        "requests_ok": ok,
        "errors": errors,
        "error_rate": err_rate,
        "rps": rps,
        "latency_p50_ms": percentile(latencies_ms, 0.50),
        "latency_p95_ms": percentile(latencies_ms, 0.95),
        "latency_p99_ms": percentile(latencies_ms, 0.99),
        "latency_mean_ms": statistics.mean(latencies_ms) if latencies_ms else float("nan"),
        "latency_min_ms": min(latencies_ms) if latencies_ms else float("nan"),
        "latency_max_ms": max(latencies_ms) if latencies_ms else float("nan"),
        "latencies_ms": latencies_ms,
        "status_codes": status_codes,
        "error_kinds_json": json.dumps(error_kinds, sort_keys=True),
    }


def wait_ready(url: str, timeout_s: float = 20.0) -> None:
    import httpx

    start = time.perf_counter()
    last_err: str | None = None
    while time.perf_counter() - start < timeout_s:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return
        except Exception as e:
            last_err = str(e)
        time.sleep(0.2)
    raise RuntimeError(f"Service not ready: {url}. Last error: {last_err}")


def sample_process(proc: psutil.Process, duration_s: float, interval_s: float = 0.5) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    proc.cpu_percent(interval=None)
    start = time.perf_counter()
    while time.perf_counter() - start < duration_s:
        cpu = proc.cpu_percent(interval=None)
        mem = proc.memory_info().rss
        samples.append({"ts_s": time.perf_counter() - start, "cpu_percent": cpu, "rss_bytes": mem})
        time.sleep(interval_s)
    return samples


def run_gateway_load_suite(sut: SystemUnderTest) -> dict[str, Any]:
    proc = subprocess.Popen(
        sut.start_cmd,
        cwd=str(sut.cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    ps_proc = psutil.Process(proc.pid)
    try:
        wait_ready(sut.readiness_url, timeout_s=25.0)
        suite = [
            {
                "name": "health",
                "path": "/health" if sut.system_id == "files" else "/api/health",
                "duration_s": 10.0,
                "concurrency": 25,
                "timeout_s": 5.0,
            },
            {
                "name": "nodes",
                "path": "/api/nodes",
                "duration_s": 10.0,
                "concurrency": 10,
                "timeout_s": 15.0,
            },
        ]
        results: list[dict[str, Any]] = []
        for test in suite:
            test_duration = float(test["duration_s"])
            concurrency = int(test["concurrency"])
            timeout_s = float(test["timeout_s"])
            proc_samples: list[dict[str, Any]] = []
            def sampler() -> None:
                nonlocal proc_samples
                proc_samples = sample_process(ps_proc, test_duration)
            th = threading.Thread(target=sampler, daemon=True)
            th.start()
            load_result = asyncio.run(http_load(sut.base_url, test["path"], concurrency, test_duration, timeout_s=timeout_s))
            th.join(timeout=test_duration + 5.0)

            latencies = load_result.pop("latencies_ms")
            status_codes = load_result.pop("status_codes")
            run_id = f"{sut.system_id}-{test['name']}"
            raw_lat_path = OUT_DIR / f"latencies_{run_id}.csv"
            with raw_lat_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["latency_ms", "status_code"])
                for i, lat in enumerate(latencies):
                    w.writerow([f"{lat:.3f}", status_codes[i] if i < len(status_codes) else ""])

            proc_path = OUT_DIR / f"proc_{run_id}.csv"
            with proc_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["ts_s", "cpu_percent", "rss_bytes"])
                w.writeheader()
                for row in proc_samples:
                    w.writerow(row)

            results.append(
                {
                    "system_id": sut.system_id,
                    "system_label": sut.label,
                    "test_name": test["name"],
                    **load_result,
                    "proc_cpu_p95": percentile([s["cpu_percent"] for s in proc_samples], 0.95),
                    "proc_rss_p95_bytes": percentile([float(s["rss_bytes"]) for s in proc_samples], 0.95),
                }
            )

        return {"system": sut.system_id, "results": results}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.stdout:
            log = proc.stdout.read()
            (OUT_DIR / f"server_{sut.system_id}.log").write_text(log or "", encoding="utf-8")


def write_perf_summary_csv(perf: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for sys_run in perf:
        rows.extend(sys_run["results"])
    out = OUT_DIR / "performance_summary.csv"
    fieldnames = [
        "system_id",
        "system_label",
        "test_name",
        "path",
        "concurrency",
        "duration_s",
        "requests_total",
        "requests_ok",
        "errors",
        "error_kinds_json",
        "error_rate",
        "rps",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "latency_mean_ms",
        "latency_min_ms",
        "latency_max_ms",
        "proc_cpu_p95",
        "proc_rss_p95_bytes",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_dashboard_html() -> None:
    summary_path = OUT_DIR / "performance_summary.csv"
    html_path = OUT_DIR / "performance_dashboard.html"
    csv_text = summary_path.read_text(encoding="utf-8").replace("\\", "\\\\").replace("`", "\\`")
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>CNP Comparative Performance Dashboard</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f6f6f6; }}
    .kpi {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }}
    .card {{ border: 1px solid #ddd; padding: 10px; border-radius: 6px; }}
    .muted {{ color: #555; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>CNP Comparative Performance Dashboard</h1>
  <div class="muted">Source: performance_summary.csv (embedded)</div>
  <div id="kpis" class="kpi"></div>
  <h2>Summary</h2>
  <table id="tbl"></table>
  <script>
    const csv = `{csv_text}`;
    const lines = csv.trim().split(/\\r?\\n/);
    const headers = lines[0].split(",");
    const rows = lines.slice(1).map(l => {{
      const cols = l.split(",");
      const obj = {{}};
      headers.forEach((h, i) => obj[h] = cols[i]);
      return obj;
    }});

    function num(x) {{
      const v = Number(x);
      return Number.isFinite(v) ? v : null;
    }}

    const tbl = document.getElementById("tbl");
    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    headers.forEach(h => {{
      const th = document.createElement("th");
      th.textContent = h;
      trh.appendChild(th);
    }});
    thead.appendChild(trh);
    tbl.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach(r => {{
      const tr = document.createElement("tr");
      headers.forEach(h => {{
        const td = document.createElement("td");
        td.textContent = r[h];
        tr.appendChild(td);
      }});
      tbody.appendChild(tr);
    }});
    tbl.appendChild(tbody);

    const bySys = {{}};
    rows.forEach(r => {{
      const k = r.system_id;
      bySys[k] ??= [];
      bySys[k].push(r);
    }});
    const kpis = document.getElementById("kpis");
    Object.keys(bySys).forEach(sysId => {{
      const sysRows = bySys[sysId];
      const p95s = sysRows.map(r => num(r.latency_p95_ms)).filter(v => v !== null);
      const rpss = sysRows.map(r => num(r.rps)).filter(v => v !== null);
      const errRates = sysRows.map(r => num(r.error_rate)).filter(v => v !== null);
      const rss = sysRows.map(r => num(r.proc_rss_p95_bytes)).filter(v => v !== null);
      const card = document.createElement("div");
      card.className = "card";
      const mean = arr => arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : null;
      card.innerHTML = `
        <div><strong>${{sysId}}</strong></div>
        <div class="muted">Avg p95 latency (ms): ${{mean(p95s)?.toFixed(2) ?? "n/a"}}</div>
        <div class="muted">Avg throughput (rps): ${{mean(rpss)?.toFixed(2) ?? "n/a"}}</div>
        <div class="muted">Avg error rate: ${{mean(errRates)?.toFixed(4) ?? "n/a"}}</div>
        <div class="muted">Avg p95 RSS (MB): ${{mean(rss) ? (mean(rss)/1024/1024).toFixed(1) : "n/a"}}</div>
      `;
      kpis.appendChild(card);
    }});
  </script>
</body>
</html>"""
    html_path.write_text(html, encoding="utf-8")


def simple_python_complexity(path: Path) -> dict[str, Any]:
    text = read_text(path)
    functions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    indent: int | None = None
    for i, line in enumerate(text.splitlines(), start=1):
        if m := re.match(r"^(\s*)def\s+([a-zA-Z0-9_]+)\s*\(", line):
            if current:
                functions.append(current)
            indent = len(m.group(1))
            current = {"name": m.group(2), "line": i, "ccn": 1, "path": str(path)}
            continue
        if current is None:
            continue
        if indent is not None and line.strip() and (len(line) - len(line.lstrip())) <= indent:
            functions.append(current)
            current = None
            indent = None
            continue
        if re.search(r"\b(if|elif|for|while|except|case)\b", line):
            current["ccn"] += 1
        if " and " in line or " or " in line:
            current["ccn"] += line.count(" and ") + line.count(" or ")
    if current:
        functions.append(current)
    return {"file": str(path), "functions": functions}


def duplication_score(py_files: list[Path]) -> dict[str, Any]:
    norm_lines: list[str] = []
    for p in py_files:
        for ln in read_text(p).splitlines():
            s = ln.strip()
            if not s or s.startswith("import ") or s.startswith("from "):
                continue
            if s.startswith('"') or s.startswith("'"):
                continue
            norm_lines.append(re.sub(r"\s+", " ", s))
    total = len(norm_lines)
    if not total:
        return {"duplication_pct": 0.0, "total_lines": 0}
    counts: dict[str, int] = {}
    for ln in norm_lines:
        counts[ln] = counts.get(ln, 0) + 1
    dup_lines = sum(c for c in counts.values() if c > 1)
    return {"duplication_pct": dup_lines / total * 100.0, "total_lines": total}


def run_bandit_json(target: Path) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "bandit", "-r", str(target), "-f", "json", "-q"]
    code, out = run(cmd, cwd=ROOT_FILES)
    try:
        return {"exit_code": code, "report": json.loads(out or "{}")}
    except json.JSONDecodeError:
        return {"exit_code": code, "raw_output": out}


def run_coverage_for_prod_tests() -> dict[str, Any]:
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "pytest", "gateway/tests", "-q"]
    code, out = run(cmd, cwd=ROOT_PROD / "gateway", timeout_s=120)
    rep_code, rep_out = run([sys.executable, "-m", "coverage", "json", "-o", str(OUT_DIR / "coverage_prod.json")], cwd=ROOT_PROD / "gateway")
    return {"pytest_exit_code": code, "pytest_output": out, "coverage_json_exit_code": rep_code, "coverage_json_output": rep_out}


def build_traceability(endpoints_files: list[dict[str, str]], endpoints_prod: list[dict[str, str]]) -> list[dict[str, str]]:
    def key(ep: dict[str, str]) -> str:
        return f'{ep["method"]} {ep["path"]}'

    files_set = {key(e) for e in endpoints_files}
    prod_set = {key(e) for e in endpoints_prod}

    catalog: list[dict[str, str]] = []

    all_eps = sorted(files_set | prod_set)
    for k in all_eps:
        files_has = "yes" if k in files_set else "no"
        prod_has = "yes" if k in prod_set else "no"
        status = "identical" if files_has == "yes" and prod_has == "yes" else ("missing" if files_has == "no" else "degraded")
        if files_has == "no" and prod_has == "yes":
            status = "enhanced"
        catalog.append(
            {
                "item_type": "api_endpoint",
                "item": k,
                "files_present": files_has,
                "prod_present": prod_has,
                "parity": status,
            }
        )

    capabilities = [
        ("user", "Node registration", "HTTP /api/node/hello", "files", "prod"),
        ("user", "Heartbeat ingest", "HTTP /api/node/heartbeat", "files", "prod"),
        ("user", "Event ingest", "HTTP /api/node/event", "files", "prod"),
        ("user", "Error ingest", "HTTP /api/node/error", "files", "prod"),
        ("admin", "List nodes", "GET /api/nodes", "files", "prod"),
        ("admin", "Get node detail", "GET /api/nodes/{node_id}", "files", "prod"),
        ("admin", "Issue command", "POST /api/commands vs POST /api/nodes/{node_id}/commands", "files", "prod"),
        ("admin", "Update node config", "PATCH /api/nodes/{node_id}/config", "files", "prod"),
        ("admin", "Recent alerts", "GET /api/alerts", "files", "prod"),
        ("user", "Command round-trip", "polling vs MQTT command topics", "files", "prod"),
        ("user", "Offline detection", "offline_watcher updates node status", "files", "prod"),
    ]
    for kind, name, impl, _, _ in capabilities:
        files_status = "yes" if name in {"List nodes", "Get node detail", "Offline detection"} else "partial"
        prod_status = "partial"
        if name in {"List nodes", "Get node detail", "Offline detection"}:
            files_status = "yes"
            prod_status = "yes"
        if name == "Issue command":
            files_status = "yes"
            prod_status = "yes"
        if name in {"Node registration", "Heartbeat ingest", "Event ingest", "Error ingest", "Command round-trip"}:
            files_status = "yes"
            prod_status = "yes"
        if name in {"Update node config", "Recent alerts"}:
            files_status = "yes"
            prod_status = "no"
        parity = "identical"
        if files_status == prod_status == "yes":
            if name in {"Node registration", "Heartbeat ingest", "Event ingest", "Error ingest", "Command round-trip"}:
                parity = "degraded"
            else:
                parity = "identical"
        elif files_status == "yes" and prod_status == "no":
            parity = "missing"
        elif files_status == "no" and prod_status == "yes":
            parity = "enhanced"
        catalog.append(
            {
                "item_type": f"capability_{kind}",
                "item": name,
                "files_present": files_status,
                "prod_present": prod_status,
                "parity": parity,
                "implementation_notes": impl,
            }
        )

    return catalog


def write_traceability_csv(rows: list[dict[str, str]]) -> None:
    out = OUT_DIR / "traceability_matrix.csv"
    fieldnames = ["item_type", "item", "files_present", "prod_present", "parity", "implementation_notes"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def build_gap_matrix(trace_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for r in trace_rows:
        if r["parity"] in {"missing", "degraded"}:
            impact = "High" if "auth" in r["item"].lower() else ("Med" if r["item_type"].startswith("api_") else "High")
            effort = "2" if r["item_type"].startswith("api_") else "5"
            risk = "Med"
            owner = "Gateway"
            row_tag = "quick_win" if effort in {"1", "2"} and impact in {"Med", "High"} else "debt_hotspot"
            gaps.append(
                {
                    "Functionality": r["item"],
                    "Current State": "prod",
                    "Target State": "parity",
                    "Impact": impact,
                    "Effort (person-days)": effort,
                    "Risk": risk,
                    "Owner": owner,
                    "Tag": row_tag,
                    "Color": "#ffd966" if row_tag == "quick_win" else "#f4cccc",
                }
            )
    return gaps


def write_gap_matrix_csv(rows: list[dict[str, str]]) -> None:
    out = OUT_DIR / "gap_analysis_matrix.csv"
    fieldnames = ["Functionality", "Current State", "Target State", "Impact", "Effort (person-days)", "Risk", "Owner", "Tag", "Color"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ensure_out_dir()

    inventory: dict[str, Any] = {}

    files_gateway_path = ROOT_FILES / "gateway.py"
    prod_main_path = ROOT_PROD / "gateway" / "app" / "main.py"
    prod_routes_path = ROOT_PROD / "gateway" / "app" / "api" / "routes.py"
    prod_db_path = ROOT_PROD / "gateway" / "app" / "core" / "db.py"
    prod_mqtt_path = ROOT_PROD / "gateway" / "app" / "core" / "mqtt_client.py"

    endpoints_files = extract_gateway_endpoints_files_gateway(files_gateway_path)
    endpoints_prod = extract_gateway_endpoints_prod(ROOT_PROD / "gateway")

    inventory["files"] = {
        "gateway": {
            "framework": "FastAPI",
            "entrypoint": str(files_gateway_path),
            "endpoints": endpoints_files,
            "integrations": extract_integrations_files_gateway(read_text(files_gateway_path)),
        },
        "database": parse_sqlite_schema_node_registry(read_text(ROOT_FILES / "node_registry.sql")),
        "schemas": {"cnp_v1_schemas.json": json.loads(read_text(ROOT_FILES / "cnp_v1_schemas.json"))},
        "firmware": {"style": "Arduino sketch", "entrypoint": str(ROOT_FILES / "cnp_node_skeleton.ino")},
    }

    inventory["prod"] = {
        "gateway": {
            "framework": "FastAPI",
            "entrypoint": str(prod_main_path),
            "routes": str(prod_routes_path),
            "endpoints": endpoints_prod,
            "integrations": extract_integrations_prod_gateway(),
        },
        "database": parse_sqlite_schema_from_python_literal(read_text(prod_db_path)),
        "mqtt": {
            **extract_mqtt_topics_prod(read_text(prod_mqtt_path)),
            "config": extract_mqtt_config_prod(),
        },
        "dependencies": {"python": extract_python_requirements_files(ROOT_PROD)},
        "firmware": {"style": "PlatformIO C++", "platformio": str(ROOT_PROD / "firmware" / "platformio.ini")},
    }

    write_json(OUT_DIR / "inventory.json", inventory)

    openapi_files = extract_openapi_from_files_gateway()
    openapi_prod = extract_openapi_from_prod_gateway()
    write_json(OUT_DIR / "openapi_files_gateway.json", openapi_files)
    write_json(OUT_DIR / "openapi_prod_gateway.json", openapi_prod)

    trace = build_traceability(endpoints_files, endpoints_prod)
    write_traceability_csv(trace)

    gap = build_gap_matrix(trace)
    write_gap_matrix_csv(gap)

    perf_runs: list[dict[str, Any]] = []
    perf_runs.append(run_gateway_load_suite(FILES_GATEWAY))
    perf_runs.append(run_gateway_load_suite(PROD_GATEWAY))
    write_perf_summary_csv(perf_runs)
    write_dashboard_html()

    py_files_files = glob_text_files(ROOT_FILES, ["*.py"])
    py_files_prod = glob_text_files(ROOT_PROD / "gateway", ["**/*.py"])

    quality = {
        "files": {
            "complexity": [simple_python_complexity(p) for p in py_files_files],
            "duplication": duplication_score(py_files_files),
            "bandit": run_bandit_json(ROOT_FILES),
        },
        "prod": {
            "complexity": [simple_python_complexity(p) for p in py_files_prod],
            "duplication": duplication_score(py_files_prod),
            "bandit": run_bandit_json(ROOT_PROD / "gateway"),
            "coverage": run_coverage_for_prod_tests(),
        },
    }
    write_json(OUT_DIR / "quality_reports.json", quality)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
