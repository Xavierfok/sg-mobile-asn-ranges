"""sg-ip-check: classify IPs against the bundled Singapore carrier dataset.

    sg-ip-check 119.234.8.104
    sg-ip-check 119.56.16.102 8.8.8.8 --json
    sg-ip-check --me            # looks up your own public IP (one call to api.ipify.org)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from . import __version__, lookup


def my_ip() -> str:
    with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
        return r.read().decode().strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sg-ip-check", description="Is this IP a Singapore mobile IP?")
    ap.add_argument("ips", nargs="*", help="IPv4 or IPv6 addresses")
    ap.add_argument("--me", action="store_true", help="also check this machine's public IP")
    ap.add_argument("--json", action="store_true", help="print JSON lines")
    ap.add_argument("--version", action="version", version=f"sg-ip-check {__version__}")
    args = ap.parse_args(argv)

    ips = list(args.ips)
    if args.me:
        ips.append(my_ip())
    if not ips:
        ap.error("give at least one IP, or --me")

    status = 0
    for ip in ips:
        try:
            r = lookup(ip)
        except ValueError:
            print(f"{ip}: not an IP address", file=sys.stderr)
            status = 2
            continue
        if args.json:
            print(json.dumps(r.to_dict(), ensure_ascii=False))
        else:
            print(r.summary)
    return status


if __name__ == "__main__":
    sys.exit(main())
