"""Проверка сервера админки без логина: статика, закрытые файлы, отказ API без токена, сериализация черновика."""
import os, sys, json, time, subprocess, urllib.request, urllib.error
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
PORT = 3099

env = dict(os.environ, ADMIN_PORT=str(PORT), PYTHONIOENCODING="utf-8")
p = subprocess.Popen([sys.executable, str(ROOT / "core" / "admin_server.py")], cwd=ROOT, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
time.sleep(4)


def req(path, method="GET", data=None, headers=None):
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


try:
    for path, want in [("/admin.html", 200), ("/api/ping", 200), ("/.env", 404), ("/credentials/x.json", 404),
                       ("/core/sb.py", 404), ("/Ретро_Excel/", 404)]:
        code, body = req(urllib.parse.quote(path))
        print(f"GET {path:<22} -> {code} {'OK' if code == want else 'ОШИБКА, ждали ' + str(want)}")
    code, body = req("/api/upload", "POST", b"PK..", {"X-Filename": "x.xlsx"})
    print(f"POST /api/upload без токена -> {code} {'OK' if code == 401 else 'ОШИБКА'} {body[:80].decode('utf-8', 'replace')}")
    code, body = req("/api/upload", "POST", b"PK..", {"X-Filename": "x.xlsx", "Authorization": "Bearer fake"})
    print(f"POST /api/upload с поддельным токеном -> {code} {'OK' if code == 401 else 'ОШИБКА'}")
finally:
    p.terminate()

import admin_server
from import_facts_to_db import build_plan
pj = admin_server.plan_to_json(build_plan(ROOT / "Ретро_Excel" / "Ретро Бонусы 2026-09-11.xlsx", "2026"))
s = json.dumps(pj, ensure_ascii=False, default=str)
print(f"черновик: {len(s)} байт JSON | строк {len(pj['rows'])} (новых {sum(r['kind']=='new' for r in pj['rows'])}, "
      f"конфликтов {sum(r['kind']=='conflict' for r in pj['rows'])}) | бонусов {len(pj['openings'])} | "
      f"контроль {'OK' if all(c['ok'] for c in pj['control']) else 'НЕТ'}")
print("пример конфликта:", json.dumps(next(r for r in pj['rows'] if r['kind'] == 'conflict'), ensure_ascii=False))
