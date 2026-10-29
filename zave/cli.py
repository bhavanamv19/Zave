"""python -m zave.cli <command>

collect   [--source citi|hsbc|all] [--details]   fetch pages politely -> data/raw_offers.jsonl
normalise [--llm]                                raw -> canonical offers in SQLite (+ review queue)
search    "lulu" [--wallet a,b] [--basket N]     wallet-aware ranked search
report                                           counts, freshness, review queue
eval      [--llm]                                extraction accuracy vs tests/gold.jsonl
demo                                             offline: normalise tests/fixtures and run sample searches
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import normalise as N
from . import store
from .crawl import PoliteFetcher, RobotsBlocked
from .search import search
from .sources import RawOffer, citi, hsbc

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_offers.jsonl"
FIX = ROOT / "tests" / "fixtures"


def cmd_collect(a):
    f = PoliteFetcher()
    raws: list[RawOffer] = []
    for name, mod, kw in (("citi", citi, {}), ("hsbc", hsbc, {"details": a.details})):
        if a.source not in (name, "all"):
            continue
        try:
            got = mod.collect(f, **kw)
        except RobotsBlocked as e:
            print(f"[{name}] robots.txt disallows {e}; skipped", file=sys.stderr)
            continue
        print(f"[{name}] {len(got)} raw blocks")
        if len(got) == 0:
            print(f"[{name}] ALERT: zero blocks - layout changed or blocked", file=sys.stderr)
        raws += got
    RAW.parent.mkdir(exist_ok=True)
    RAW.write_text("\n".join(json.dumps(asdict(r)) for r in raws), encoding="utf-8")


def load_raw(path: Path = RAW) -> list[RawOffer]:
    return [RawOffer(**json.loads(l)) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run_normalise(raws: list[RawOffer], c, use_llm: bool):
    offers, review = [], 0
    for r in raws:
        o, why = N.normalise(r, use_llm)
        if o is not None:
            offers.append(o)
        if why:
            store.log_review(c, r, why)
            review += 1
        if use_llm:
            import time
            time.sleep(2.2)     # Groq free tier is rate-limited; stay well under it
    stats = store.upsert_offers(c, offers)
    for src in {r.source for r in raws}:
        n = sum(1 for r in raws if r.source == src)
        prev = c.execute("SELECT blocks FROM source_runs WHERE source=? ORDER BY id DESC LIMIT 1", (src,)).fetchone()
        if prev and n < 0.5 * prev["blocks"]:
            print(f"ALERT [{src}]: blocks dropped {prev['blocks']} -> {n}", file=sys.stderr)
        c.execute("INSERT INTO source_runs(source,ts,blocks,normalised,review) VALUES(?,datetime('now'),?,?,?)",
                  (src, n, sum(1 for o in offers if o.source == src), review))
    c.commit()
    print(f"normalised {len(offers)}/{len(raws)}; review queue +{review}; {stats}")


def cmd_normalise(a):
    raws = load_raw()
    c = store.connect()
    run_normalise(raws, c, a.llm)
    if raws:
        c.execute("DELETE FROM app_metadata WHERE key='fixture_preview'")
        c.commit()


def _print(results):
    for i, r in enumerate(results, 1):
        left = f"{r.days_left}d left" if r.days_left is not None else "no expiry"
        print(f"{i:>2}. {r.merchant:<34} ~AED {r.expected_saving:>6.0f}  [{left}]  {r.title[:60]}")
        print(f"      {r.eligibility}" + (" | " + "; ".join(r.caveats) if r.caveats else ""))


def cmd_search(a):
    c = store.connect()
    _print(search(c, a.query, [w for w in (a.wallet or "").split(",") if w], a.basket))


def cmd_report(a):
    c = store.connect()
    for r in c.execute("SELECT source, status, COUNT(*) n, MIN(last_verified) oldest FROM offers GROUP BY source,status"):
        print(dict(r))
    print("review queue (open):", c.execute("SELECT COUNT(*) FROM review_queue WHERE resolved=0").fetchone()[0])
    for r in c.execute("SELECT reason, COUNT(*) n FROM review_queue WHERE resolved=0 GROUP BY reason ORDER BY n DESC LIMIT 8"):
        print("  ", r["n"], r["reason"])


def cmd_web(a):
    from .web import serve
    serve(a.host, a.port)


def cmd_eval(a):
    gold = [json.loads(l) for l in (ROOT / "tests" / "gold.jsonl").read_text().splitlines() if l.strip()]
    fields = ["benefit_type", "value", "cap_aed", "min_spend_aed", "valid_to"]
    hits = {f: 0 for f in fields}
    for g in gold:
        raw = RawOffer(g["source"], "gold", g["issuer"], g["title"], g["text"], g.get("section", ""))
        o, _ = N.normalise(raw, a.llm)
        for f in fields:
            got = getattr(o, f, None) if o else None
            got = got.value if hasattr(got, "value") else (got.isoformat() if hasattr(got, "isoformat") else got)
            exp = g["expect"].get(f)
            hits[f] += int(got == exp)
    n = len(gold)
    print(f"gold items: {n} (hand-labelled by the author from captured page text; small sample, not a benchmark)")
    for f in fields:
        print(f"  {f:<14} {hits[f]}/{n} = {hits[f]/n:.0%}")
    print(f"  all-fields-correct items: computed per field above; overall field accuracy {sum(hits.values())/(n*len(fields)):.0%}")


def cmd_demo(a):
    import tempfile
    db = Path(tempfile.mkdtemp()) / "demo.db"
    c = store.connect(db)
    raws = citi.parse((FIX / "citi_promotions.html").read_text(encoding="utf-8")) + \
        hsbc.parse_list((FIX / "hsbc_special_offers_p1.html").read_text(encoding="utf-8"))
    print(f"fixture blocks: {len(raws)}")
    run_normalise(raws, c, False)
    for q, w in (("radisson", ["citi_other_credit"]), ("cinema", ["citi_ultima"]), ("spa", ["hsbc_premier"]), ("dubai", [])):
        print(f"\n> search {q!r} wallet={w}")
        _print(search(c, q, w)[:4])


def main():
    p = argparse.ArgumentParser(prog="zave")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect"); s.add_argument("--source", default="all"); s.add_argument("--details", action="store_true"); s.set_defaults(f=cmd_collect)
    s = sub.add_parser("normalise"); s.add_argument("--llm", action="store_true"); s.set_defaults(f=cmd_normalise)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--wallet"); s.add_argument("--basket", type=float); s.set_defaults(f=cmd_search)
    s = sub.add_parser("report"); s.set_defaults(f=cmd_report)
    s = sub.add_parser("web"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(f=cmd_web)
    s = sub.add_parser("eval"); s.add_argument("--llm", action="store_true"); s.set_defaults(f=cmd_eval)
    s = sub.add_parser("demo"); s.set_defaults(f=cmd_demo)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
