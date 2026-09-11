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
"""
import os, sys, json, time, uuid, hashlib, threading, subprocess, urllib.request, urllib.parse
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb
from paths import ROOT, EXCEL_DIR
from import_facts_to_db import build_plan, apply_plan

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
                "payment_date": rec.get("payment_date"), "flags": flags,
                "extra": [f"{e['amount']:,.0f} {e['label']}".replace(",", " ") for e in rec.get("additional_payments") or []],
                "default": kind == "new" and not flags})
    openings = [{"cell": o["cell"], "excel_name": o["rec"]["excel_name"], "store": o["rec"]["store_label"],
                 "amount": o["rec"]["amount"], "state": o["state"], "previous": o["amount_previous"],
                 "supplier": sup.get(o["rec"]["supplier_id"]) if o["rec"]["supplier_id"] else None}
                for o in plan["openings"]]
    return {"file": plan["file"], "control": plan["control"], "same": plan["same"], "rows": rows,
            "openings": openings, "unmapped": plan["unmapped"], "skipped": plan["skipped"],
            "manual": [m[0] for m in plan["manual"]]}


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
