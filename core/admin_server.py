#!/usr/bin/env python3
"""
admin_server.py - локальный сервер админки (вместо `python -m http.server 3000`).

- Отдаёт ТОЛЬКО admin.html и иконку (старый http.server отдавал всю папку, включая .env и ключи,
  и слушал все сетевые интерфейсы). Слушает только 127.0.0.1.
- API загрузки Excel: черновик -> подтверждение -> запись пачкой с журналом -> автосверка и диагностика.
- Каждый запрос API проверяет логин админки (токен Supabase) и пишет, кто сделал.

Запуск: start_admin.bat  (или из корня: python core\\admin_server.py)
API:
  POST /api/upload                 тело = xlsx, заголовок X-Filename -> черновик (ничего не пишет в факты)
  POST /api/imports/<id>/apply     {"new_cells": [...], "conflict_cells": [...], "openings": true}
  POST /api/imports/<id>/cancel
  POST /api/reconcile              пересверить без загрузки
  GET  /api/jobs/<id>              ход сверки
  GET  /api/data-health            светофор по данным: агрегат output\\data_health_2026.csv (bq_docs.health)
  GET  /api/sku-coverage           позиционный отчёт: output\\sku_coverage_2026.csv (tools\\sku_coverage.py)
                                   ?view=summary|pair|top&supplier=&month=
"""
import os, sys, csv, json, time, uuid, hashlib, threading, subprocess, urllib.request, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb
from paths import ROOT, OUT, EXCEL_DIR
from import_facts_to_db import build_plan, apply_plan, note_body

HOST, PORT = "127.0.0.1", int(os.environ.get("ADMIN_PORT", "3000"))
STATIC = {"/admin.html": ROOT / "admin.html"}
MAX_UPLOAD = 20 * 1024 * 1024
_auth_cache, _jobs, _lock = {}, {}, threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def user_from_token(token):
    """Проверка сессии админки через Supabase Auth. -> email или None."""
    if not token:
        return None
    hit = _auth_cache.get(token)
    if hit and hit[1] > time.time():
        return hit[0]
    req = urllib.request.Request(f"{sb.URL}/auth/v1/user",
                                 headers={"apikey": sb.KEY, "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            email = json.loads(r.read()).get("email") or "user"
    except Exception:
        return None
    _auth_cache[token] = (email, time.time() + 300)
    return email


def plan_to_json(plan):
    sup = plan["sup"]
    rows = []
    for kind, lst in (("new", plan["new"]), ("conflict", plan["conflict"])):
        for cell, raw, rec, flags in lst:
            rows.append({
                "cell": cell, "kind": kind, "excel_name": raw, "supplier": sup.get(rec["supplier_id"], "?"),
                "period": rec["period_label"], "amount": rec["amount_paid"], "previous": rec.get("amount_previous"),
                "payment_date": rec.get("payment_date"), "flags": flags, "note": note_body(rec.get("notes") or ""),
                "extra": [f"{e['amount']:,.0f} {e['label']}".replace(",", " ") for e in rec.get("additional_payments") or []],
                "default": kind == "new" and not flags})
    openings = [{"cell": o["cell"], "excel_name": o["rec"]["excel_name"], "store": o["rec"]["store_label"],
                 "amount": o["rec"]["amount"], "state": o["state"], "previous": o["amount_previous"],
                 "supplier": sup.get(o["rec"]["supplier_id"]) if o["rec"]["supplier_id"] else None}
                for o in plan["openings"]]
    spread = [{k: b[k] for k in ("supplier", "months", "excel_total", "admin_total", "cells", "notes")}
              for b in plan.get("spread") or []]
    return {"file": plan["file"], "control": plan["control"], "same": plan["same"], "rows": rows,
            "openings": openings, "spread": spread, "unmapped": plan["unmapped"], "skipped": plan["skipped"],
            "manual": [m[0] for m in plan["manual"]]}


def data_health(retro_only=True):
    """Светофор по данным: агрегат последнего отчёта bq_docs.health() (output\\data_health_2026.csv).
    Ничего не считает заново - отчёт пишется в конце reconcile_facts.py --apply.
    retro_only=True - только поставщики, по которым есть ретро (колонка «в ретро» отчёта)."""
    p = OUT / "data_health_2026.csv"
    if not p.exists():
        return {"ok": False, "error": "отчёта ещё нет - запустите «⟳ Пересверить»"}
    import bq_docs
    retro = bq_docs.retro_alias_names()   # свежий список: алиас + активное правило, а не просто алиас
    months, rows = {}, []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            is_retro = r["поставщик BQ"] in retro
            if retro_only and not is_retro:
                continue
            kind, per, typ = r["вид"], r["месяц"], r["тип"]
            n, d = int(r["документов"] or 0), float(r["эталон - наши"] or 0)
            t = months.setdefault(per, {"per": per, "inc": {}, "ret": {}})[kind].setdefault(
                typ, {"ru": r["тип_ru"], "n": 0, "delta": 0.0, "days": []})
            t["n"] += n
            t["delta"] = round(t["delta"] + d, 2)
            # «даты» отчёта - «дд.мм» или «дд.мм-дд.мм»: внутри месяца края берутся сортировкой по дню
            t["days"] += [x for x in (r.get("даты") or "").split("-") if x]
            rows.append({"kind": kind, "per": per, "supplier": r["поставщик BQ"], "type": typ, "retro": is_retro,
                         "docs": n, "delta": round(d, 2), "sample": (r["примеры"] or "")[:160],
                         "dates": r.get("даты") or "", "numbers": r.get("номера") or ""})
    for m in months.values():
        for k in ("inc", "ret"):
            for t in m[k].values():
                dd = sorted(t.pop("days"))
                t["range"] = "" if not dd else (dd[0] if dd[0] == dd[-1] else f"{dd[0]}-{dd[-1]}")
    return {"ok": True, "file": p.name, "retro_only": retro_only,
            "updated": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="minutes"),
            "months": [months[k] for k in sorted(months)],
            "top": sorted(rows, key=lambda x: -abs(x["delta"]))[:8]}


_sku_cache = {"mtime": None, "rows": None}
SKU_NO_ESTIMATE = "покрыт правилом другого поставщика"   # оценка «недосчитано» там невалидна
SKU_KINDS = ("вне правил", "сырьё", "исключён правилом")


def _sku_rows():
    """Строки позиционного отчёта из output\\sku_coverage_2026.csv (пишет tools\\sku_coverage.py). Кеш по mtime."""
    p = OUT / "sku_coverage_2026.csv"
    if not p.exists():
        return None, None
    m = p.stat().st_mtime
    if _sku_cache["mtime"] != m:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            _sku_cache["rows"] = list(csv.DictReader(fh, delimiter=";"))
        _sku_cache["mtime"] = m
    return _sku_cache["rows"], p


def sku_coverage(view="summary", supplier=None, month=None):
    """Позиционный отчёт для админки. Ничего не считает: читает готовый CSV (BigQuery не трогаем).
    view: summary - сводка поставщик x месяц; pair - позиции одной пары; top - топ-50 без флагов месяца."""
    rows, p = _sku_rows()
    if rows is None:
        return {"ok": False, "error": "отчёта ещё нет - запустите: python tools\\sku_coverage.py"}
    num = lambda r, k: float(r[k] or 0)
    head = {"ok": True, "file": p.name, "truth_until": "2026-06",
            "updated": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="minutes")}
    if view == "pair":
        sel = [r for r in rows if r["поставщик"] == supplier and r["месяц"] == month]
        sel.sort(key=lambda r: (-num(r, "недосчитано"), -num(r, "приход")))
        head["rows"] = [{"bc": r["баркод"], "name": r["наименование"], "brand": r["бренд"], "status": r["статус покрытия"],
                         "rule": r["правило"], "period": r["период правила"], "rate": r["ставка %"],
                         "qty": r["количество"], "inc": num(r, "приход"), "ret": num(r, "возвраты"),
                         "base": num(r, "база"), "retro": num(r, "ретро посчитано"),
                         "under": num(r, "недосчитано") if not r["статус покрытия"].startswith(SKU_NO_ESTIMATE) else None,
                         "drift": r["дрейф"]} for r in sel[:800]]
        head["total"] = len(sel)
        head["flags"] = sel[0]["флаги месяца"] if sel else ""
        return head
    agg = {}
    for r in rows:
        k = (r["поставщик"], r["месяц"])
        a = agg.setdefault(k, {"supplier": r["поставщик"], "per": r["месяц"], "base": 0.0, "retro": 0.0,
                               "under": {x: 0.0 for x in SKU_KINDS}, "n": defaultdict(int),
                               "flags": r["флаги месяца"], "rows": 0})
        st = r["статус покрытия"].split(";")[0]
        a["rows"] += 1
        a["base"] += num(r, "база")
        a["retro"] += num(r, "ретро посчитано")
        a["n"][st] += 1
        if st in SKU_KINDS and not r["статус покрытия"].startswith(SKU_NO_ESTIMATE):
            a["under"][st] += num(r, "недосчитано")
    for a in agg.values():
        a["base"], a["retro"] = round(a["base"], 2), round(a["retro"], 2)
        a["under"] = {k: round(v, 2) for k, v in a["under"].items()}
        a["n"] = dict(a["n"])
        a["flagged"] = ("недогруз" in a["flags"]) or ("задвоено" in a["flags"])
        a["truth"] = a["per"] <= head["truth_until"]
    if view == "top":
        ok_pairs = {k for k, a in agg.items() if not a["flagged"]}
        sel = [r for r in rows if (r["поставщик"], r["месяц"]) in ok_pairs and num(r, "недосчитано") > 0
               and not r["статус покрытия"].startswith(SKU_NO_ESTIMATE)]
        sel.sort(key=lambda r: -num(r, "недосчитано"))
        head["rows"] = [{"per": r["месяц"], "supplier": r["поставщик"], "bc": r["баркод"], "name": r["наименование"],
                         "status": r["статус покрытия"], "under": num(r, "недосчитано"),
                         "inc": num(r, "приход"), "truth": r["месяц"] <= head["truth_until"]} for r in sel[:50]]
        return head
    head["pairs"] = sorted(agg.values(), key=lambda a: (a["per"], -sum(a["under"].values())))
    return head


def store_file(data, filename):
    """Сохранить в Ретро_Excel; если такой файл (по sha256) уже лежит - использовать его."""
    h = hashlib.sha256(data).hexdigest()
    EXCEL_DIR.mkdir(exist_ok=True)
    for p in EXCEL_DIR.rglob("*.xlsx"):
        try:
            if p.stat().st_size == len(data) and hashlib.sha256(p.read_bytes()).hexdigest() == h:
                return p, h
        except OSError:
            pass
    safe = "".join(ch for ch in Path(filename).name if ch not in '<>:"/\\|?*').strip() or "retro.xlsx"
    dst = EXCEL_DIR / f"{datetime.now():%Y-%m-%d %H%M} {safe}"
    dst.write_bytes(data)
    return dst, h


def start_job(kind, who):
    with _lock:
        for jid, j in _jobs.items():
            if j["status"] == "running":
                return jid
        jid = str(uuid.uuid4())
        _jobs[jid] = {"kind": kind, "status": "running", "started": now(), "by": who, "log": []}

    def work():
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, str(ROOT / "core" / "reconcile_facts.py"), "--apply"]
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", env=env)
            for line in p.stdout:
                _jobs[jid]["log"].append(line.rstrip())
                del _jobs[jid]["log"][:-200]
            code = p.wait()
            _jobs[jid]["status"] = "done" if code == 0 else "failed"
        except Exception as e:
            _jobs[jid]["log"].append(f"ошибка запуска: {e}")
            _jobs[jid]["status"] = "failed"
        _jobs[jid]["finished"] = now()

    threading.Thread(target=work, daemon=True).start()
    return jid


class Handler(BaseHTTPRequestHandler):
    server_version = "RetroAdmin/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[{datetime.now():%H:%M:%S}] {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def who(self):
        auth = self.headers.get("Authorization", "")
        return user_from_token(auth[7:] if auth.startswith("Bearer ") else "")

    def read_body(self, limit=MAX_UPLOAD):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError(f"файл больше {limit // 1024 // 1024} МБ")
        return self.rfile.read(n)

    # ── GET ──
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/admin.html")
            self.end_headers()
            return
        if path in STATIC:
            data = STATIC[path].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/ping":
            return self.send_json(200, {"ok": True})
        if path == "/api/data-health":
            if not self.who():
                return self.send_json(401, {"error": "нужен вход в админку"})
            scope = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("scope", ["retro"])[0]
            return self.send_json(200, data_health(retro_only=scope != "all"))
        if path == "/api/sku-coverage":
            if not self.who():
                return self.send_json(401, {"error": "нужен вход в админку"})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.send_json(200, sku_coverage(view=q.get("view", ["summary"])[0],
                                                    supplier=q.get("supplier", [None])[0],
                                                    month=q.get("month", [None])[0]))
        if path.startswith("/api/jobs/"):
            if not self.who():
                return self.send_json(401, {"error": "нужен вход в админку"})
            j = _jobs.get(path.rsplit("/", 1)[-1])
            return self.send_json(200 if j else 404, j or {"error": "нет такой задачи"})
        self.send_response(404)
        self.end_headers()

    # ── POST ──
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        who = self.who()
        if not who:
            return self.send_json(401, {"error": "нужен вход в админку (сессия истекла - обновите страницу)"})
        try:
            if path == "/api/upload":
                return self.upload(who)
            if path == "/api/reconcile":
                return self.send_json(200, {"job_id": start_job("reconcile", who)})
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "imports"] and parts[3] in ("apply", "cancel"):
                return self.apply(parts[2], who) if parts[3] == "apply" else self.cancel(parts[2], who)
            self.send_json(404, {"error": "неизвестный адрес"})
        except Exception as e:
            self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def upload(self, who):
        data = self.read_body()
        name = urllib.parse.unquote(self.headers.get("X-Filename") or "retro.xlsx")
        if not data.startswith(b"PK"):
            return self.send_json(400, {"error": "это не файл .xlsx"})
        path, h = store_file(data, name)
        try:
            plan = build_plan(path, "2026")
        except KeyError:
            return self.send_json(400, {"error": "в файле нет листа «2026»"})
        pj = plan_to_json(plan)
        prev = sb.get("retro_fact_imports", f"file_hash=eq.{h}&status=eq.applied&select=applied_at,applied_by"
                      "&order=applied_at.desc&limit=1")
        summary = {"new": sum(1 for r in pj["rows"] if r["kind"] == "new"),
                   "conflict": sum(1 for r in pj["rows"] if r["kind"] == "conflict"), "same": pj["same"],
                   "spread": len(pj["spread"]),
                   "openings_new": sum(1 for o in pj["openings"] if o["state"] != "same"),
                   "control_ok": all(c["ok"] for c in pj["control"]), "unmapped": pj["unmapped"]}
        row = sb.upsert("retro_fact_imports", [{"file_name": name, "stored_path": str(path.relative_to(ROOT)),
                                                "file_hash": h, "status": "draft", "uploaded_by": who,
                                                "summary": summary}])[0]
        pj.update(import_id=row["id"], stored=str(path.relative_to(ROOT)), hash=h[:12],
                  repeat=prev[0] if prev else None, summary=summary)
        self.send_json(200, pj)

    def apply(self, import_id, who):
        body = json.loads(self.read_body(1024 * 1024) or b"{}")
        imp = sb.get("retro_fact_imports", f"id=eq.{import_id}&select=*")
        if not imp:
            return self.send_json(404, {"error": "черновик не найден"})
        imp = imp[0]
        if imp["status"] != "draft":
            return self.send_json(409, {"error": f"черновик уже в статусе {imp['status']}"})
        # план пересобирается на СВЕЖЕЙ базе: если кто-то успел внести вручную - строка станет «совпадает»/конфликтом
        plan = build_plan(ROOT / imp["stored_path"], "2026")
        if not all(c["ok"] for c in plan["control"]):
            return self.send_json(400, {"error": "контрольные суммы файла не сходятся - запись запрещена"})
        new_cells = set(body.get("new_cells") or []) & {x[0] for x in plan["new"]}
        conflict_cells = set(body.get("conflict_cells") or []) & {x[0] for x in plan["conflict"]}
        dropped = (set(body.get("new_cells") or []) - new_cells) | (set(body.get("conflict_cells") or []) - conflict_cells)
        written = apply_plan(plan, new_cells=new_cells, conflict_cells=conflict_cells,
                             openings=bool(body.get("openings", True)))
        applied = {"new_cells": sorted(new_cells), "conflict_cells": sorted(conflict_cells),
                   "dropped_changed_meanwhile": sorted(dropped), "written": written,
                   "amount": round(sum(x[2]["amount_paid"] for x in plan["new"] if x[0] in new_cells) +
                                   sum(x[2]["amount_paid"] for x in plan["conflict"] if x[0] in conflict_cells), 2)}
        sb._req(f"{sb.URL}/rest/v1/retro_fact_imports?id=eq.{import_id}",
                {"status": "applied", "applied_by": who, "applied_at": now(), "applied": applied},
                "PATCH", {"Prefer": "return=minimal"})
        self.send_json(200, {"applied": applied, "job_id": start_job("reconcile", who)})

    def cancel(self, import_id, who):
        sb._req(f"{sb.URL}/rest/v1/retro_fact_imports?id=eq.{import_id}&status=eq.draft",
                {"status": "cancelled", "applied_by": who, "applied_at": now()}, "PATCH", {"Prefer": "return=minimal"})
        self.send_json(200, {"ok": True})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[i] Админка: http://localhost:{PORT}/admin.html  (только этот компьютер; Ctrl+C - остановить)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
