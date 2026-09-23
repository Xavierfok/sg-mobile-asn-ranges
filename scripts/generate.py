#!/usr/bin/env python3
"""Rebuild data/ from sources/asns.json plus live BGP data from RIPEstat.

For every curated ASN this fetches the registry holder name (as-overview) and
the prefixes it currently announces (announced-prefixes), then writes:

  data/sg-asns.json                  full dataset, one record per ASN
  data/sg-prefixes.csv               one row per prefix
  data/cidr/<carrier>.txt            every prefix for that carrier
  data/cidr/<carrier>-mobile.txt     only prefixes from ASNs with role=mobile
  data/cidr/all-mobile-ipv4.txt      every mobile IPv4 prefix
  data/cidr/all-mobile-ipv6.txt      every mobile IPv6 prefix
  src/sg_ip_check/data/sg-asns.json  copy bundled with the Python package

Files are rewritten only when the prefixes or metadata actually change, so a
weekly run with nothing new produces no diff and no commit.

A sanity guard refuses to write if the total prefix count drops by more than
MAX_DROP, or an ASN that had prefixes suddenly has none. That usually means
RIPEstat had a bad moment, not that a carrier vanished. Pass --force to
override after checking by hand.
"""
from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources" / "asns.json"
DATA = ROOT / "data"
PKG_DATA = ROOT / "src" / "sg_ip_check" / "data" / "sg-asns.json"

RIPESTAT = "https://stat.ripe.net/data/{endpoint}/data.json?resource=AS{asn}&sourceapp=sg-mobile-asn-ranges"
MAX_DROP = 0.25
USER_AGENT = "sg-mobile-asn-ranges (+https://github.com/Xavierfok/sg-mobile-asn-ranges)"


def fetch_json(url: str, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # network blips are common; retry with backoff
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch_asn(asn: int, fetch=fetch_json) -> dict:
    overview = fetch(RIPESTAT.format(endpoint="as-overview", asn=asn))["data"]
    prefixes = fetch(RIPESTAT.format(endpoint="announced-prefixes", asn=asn))["data"]["prefixes"]
    v4, v6 = set(), set()
    for p in prefixes:
        net = ipaddress.ip_network(p["prefix"], strict=False)
        (v4 if net.version == 4 else v6).add(str(net))
    return {
        "holder": overview.get("holder") or "",
        "announced": bool(overview.get("announced")),
        "ipv4": sorted(v4, key=lambda s: ipaddress.ip_network(s)),
        "ipv6": sorted(v6, key=lambda s: ipaddress.ip_network(s)),
    }


def build(sources: dict, fetch=fetch_json) -> dict:
    records = []
    for entry in sorted(sources["asns"], key=lambda e: (e["carrier"], e["asn"])):
        live = fetch_asn(entry["asn"], fetch=fetch)
        records.append({
            "asn": entry["asn"],
            "carrier": entry["carrier"],
            "role": entry["role"],
            "is_mobile": True if entry["role"] == "mobile" else (None if entry["role"] == "unknown" else False),
            "confidence": entry["confidence"],
            "holder": live["holder"],
            "announced": live["announced"],
            "evidence": entry["evidence"],
            "prefixes": {"ipv4": live["ipv4"], "ipv6": live["ipv6"]},
        })
    return {
        "name": "sg-mobile-asn-ranges",
        "description": "Singapore mobile carrier ASNs and the prefixes they announce, with the evidence for each classification.",
        "source": "RIPEstat as-overview + announced-prefixes (https://stat.ripe.net), roles hand-curated in sources/asns.json",
        "license": "CC-BY-4.0 (data); RIPEstat data courtesy of the RIPE NCC",
        "asns": records,
    }


def prefix_count(ds: dict) -> int:
    return sum(len(r["prefixes"]["ipv4"]) + len(r["prefixes"]["ipv6"]) for r in ds.get("asns", []))


def sanity_problems(old: dict | None, new: dict) -> list[str]:
    if not old:
        return []
    problems = []
    before, after = prefix_count(old), prefix_count(new)
    if before and after < before * (1 - MAX_DROP):
        problems.append(f"total prefixes fell {before} -> {after} (more than {int(MAX_DROP * 100)}%)")
    old_by_asn = {r["asn"]: r for r in old.get("asns", [])}
    for r in new["asns"]:
        o = old_by_asn.get(r["asn"])
        if o and (o["prefixes"]["ipv4"] or o["prefixes"]["ipv6"]) and not (r["prefixes"]["ipv4"] or r["prefixes"]["ipv6"]):
            problems.append(f"AS{r['asn']} had prefixes and now has none")
    return problems


def comparable(ds: dict | None) -> dict | None:
    """The dataset minus fields that change on every run."""
    if ds is None:
        return None
    return {k: v for k, v in ds.items() if k != "generated_at"}


def render_outputs(ds: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    out["data/sg-asns.json"] = json.dumps(ds, indent=2, ensure_ascii=False) + "\n"

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["prefix", "family", "asn", "carrier", "role", "confidence", "holder"])
    for r in ds["asns"]:
        for fam in ("ipv4", "ipv6"):
            for p in r["prefixes"][fam]:
                w.writerow([p, fam, r["asn"], r["carrier"], r["role"], r["confidence"], r["holder"]])
    out["data/sg-prefixes.csv"] = buf.getvalue()

    def lines(prefixes):
        return "".join(p + "\n" for p in prefixes)

    carriers = sorted({r["carrier"] for r in ds["asns"]})
    all_mobile = {"ipv4": [], "ipv6": []}
    for c in carriers:
        recs = [r for r in ds["asns"] if r["carrier"] == c]
        every = [p for r in recs for fam in ("ipv4", "ipv6") for p in r["prefixes"][fam]]
        out[f"data/cidr/{c}.txt"] = lines(every)
        mob = [r for r in recs if r["role"] == "mobile"]
        if mob:
            out[f"data/cidr/{c}-mobile.txt"] = lines(p for r in mob for fam in ("ipv4", "ipv6") for p in r["prefixes"][fam])
            for r in mob:
                for fam in ("ipv4", "ipv6"):
                    all_mobile[fam].extend(r["prefixes"][fam])
    out["data/cidr/all-mobile-ipv4.txt"] = lines(sorted(set(all_mobile["ipv4"]), key=ipaddress.ip_network))
    out["data/cidr/all-mobile-ipv6.txt"] = lines(sorted(set(all_mobile["ipv6"]), key=ipaddress.ip_network))
    out[str(PKG_DATA.relative_to(ROOT)).replace("\\", "/")] = out["data/sg-asns.json"]
    return out


def main(argv=None, fetch=fetch_json, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="write even if the sanity guard objects")
    args = ap.parse_args(argv)

    sources = json.loads((root / "sources" / "asns.json").read_text(encoding="utf-8"))
    current_path = root / "data" / "sg-asns.json"
    old = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else None

    new = build(sources, fetch=fetch)
    if comparable(old) == comparable(new):
        print(f"no change ({prefix_count(new)} prefixes across {len(new['asns'])} ASNs)")
        return 0

    problems = sanity_problems(old, new)
    if problems and not args.force:
        for p in problems:
            print("REFUSING TO WRITE:", p, file=sys.stderr)
        return 2

    new["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for rel, text in render_outputs(new).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    print(f"wrote {prefix_count(new)} prefixes across {len(new['asns'])} ASNs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
