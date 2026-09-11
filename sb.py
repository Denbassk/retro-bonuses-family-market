"""sb.py - общий доступ к Supabase. Единая версия с автопагинацией и батчами."""
import os, json, urllib.request, urllib.error
from pathlib import Path


def load_env(env_path=None):
    if env_path is None:
        here = Path(__file__).parent
        for c in (here / ".env", here.parent / ".env"):
            if c.exists():
                env_path = c
                break
    if not env_path or not Path(env_path).exists():
        return
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


load_env()
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
_H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def _req(url, data=None, method="GET", extra=None):
    h = dict(_H)
    if extra:
        h.update(extra)
    body = json.dumps(data, default=str).encode() if data is not None else None
    if body:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            txt = resp.read()
            return json.loads(txt) if txt else []
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('/rest/v1/')[-1][:80]} -> "
                           f"{e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from None


def get(table, params="", page_size=1000):
    """GET с автопагинацией. Если в params есть limit/offset - один запрос."""
    if "limit=" in params or "offset=" in params:
        return _req(f"{URL}/rest/v1/{table}?{params}")
    out, offset = [], 0
    order = "" if "order=" in params else "&order=id"
    while True:
        sep = "&" if params else ""
        page = _req(f"{URL}/rest/v1/{table}?{params}{sep}limit={page_size}&offset={offset}{order}")
        if not isinstance(page, list):
            return page
        out.extend(page)
        if len(page) < page_size:
            return out
        offset += page_size


def upsert(table, rows, on_conflict=None, batch=500):
    """Батчевый upsert. rows - список словарей."""
    if isinstance(rows, dict):
        rows = [rows]
    url = f"{URL}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    pref = "return=representation,resolution=merge-duplicates" if on_conflict else "return=representation"
    out = []
    for i in range(0, len(rows), batch):
        out.extend(_req(url, rows[i:i + batch], "POST", {"Prefer": pref}) or [])
    return out
