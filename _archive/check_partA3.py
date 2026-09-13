"""A2: по AST - где определены и откуда вызываются sb_get / sb_post / load_env -> output/check_partA3.txt"""
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
NAMES = ("sb_get", "sb_post", "load_env")
defs, calls, imports = {n: [] for n in NAMES}, {n: {} for n in NAMES}, []
for p in sorted(ROOT.rglob("*.py")):
    if ".git" in p.parts or "__pycache__" in p.parts:
        continue
    try:
        t = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    rel = str(p.relative_to(ROOT))
    for node in ast.walk(t):
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            defs[node.name].append(f"{rel}:{node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in NAMES:
            calls[node.func.id][rel] = calls[node.func.id].get(rel, 0) + 1
        if isinstance(node, ast.ImportFrom) and any(a.name in NAMES for a in node.names):
            imports.append(f"{rel}:{node.lineno} from {node.module} import " + ", ".join(a.name for a in node.names))
out = []
for n in NAMES:
    out.append(f"{n}: определений {len(defs[n])} -> {', '.join(defs[n])}")
    out.append(f"   вызовы: " + ", ".join(f"{k} x{v}" for k, v in sorted(calls[n].items())))
out.append("импорты этих имён между файлами: " + ("; ".join(imports) if imports else "нет"))
(ROOT / "output" / "check_partA3.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")
