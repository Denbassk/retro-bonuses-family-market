"""Разовый: крупнейшие строки data_health_2026.csv по (вид, месяц, тип) -> output/probe_health_top.txt"""
import csv
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
rows = list(csv.reader((ROOT / "output" / "data_health_2026.csv").open(encoding="utf-8-sig"), delimiter=";"))[1:]
out = []
for kind, per, typ in (("inc", "2026-07", "extra"), ("inc", "2026-07", "double"), ("inc", "2026-08", "amount"),
                       ("inc", "2026-05", "extra"), ("inc", "2026-04", "double"), ("ret", "2026-08", "missing"),
                       ("inc", "2026-07", "missing")):
    rs = sorted([r for r in rows if r[0] == kind and r[1] == per and r[4] == typ], key=lambda r: -abs(float(r[7])))
    out.append(f"\n== {kind} {per} {typ}: поставщиков {len(rs)}, сумма {sum(float(r[7]) for r in rs):,.0f}")
    for r in rs[:8]:
        out.append(f"  {r[2][:32]:<32} ретро={r[3]:<2} {r[6]:>3} док. {float(r[7]):>12,.0f}  {r[8][:150]}")
(ROOT / "output" / "probe_health_top.txt").write_text("\n".join(out), encoding="utf-8")
