"""Is this IP a Singapore mobile IP? Offline lookup against sg-mobile-asn-ranges.

    >>> from sg_ip_check import lookup
    >>> r = lookup("119.234.8.104")
    >>> r.carrier, r.asn, r.is_mobile
    ('singtel', 45143, True)

No network calls: the dataset ships inside the package.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union

__all__ = ["Result", "lookup", "load_dataset", "Checker", "__version__"]
__version__ = "0.1.0"

_BUNDLED = Path(__file__).parent / "data" / "sg-asns.json"

CARRIER_NAMES = {"singtel": "Singtel", "m1": "M1", "starhub": "StarHub", "simba": "Simba"}


@dataclass
class Result:
    ip: str
    found: bool
    carrier: Optional[str] = None
    carrier_name: Optional[str] = None
    asn: Optional[int] = None
    holder: Optional[str] = None
    prefix: Optional[str] = None
    role: Optional[str] = None
    #: True = mobile network, False = known non-mobile carrier network,
    #: None = not in the dataset, or the ASN's role is unknown.
    is_mobile: Optional[bool] = None
    confidence: Optional[str] = None
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def summary(self) -> str:
        if not self.found:
            return f"{self.ip} is not in any Singapore carrier range this dataset tracks"
        what = {True: "a Singapore mobile IP", False: "a Singapore carrier IP, but not a mobile one",
                None: "a Singapore carrier IP of unconfirmed type"}[self.is_mobile]
        return f"{self.ip} is {what} ({self.carrier_name}, AS{self.asn}, {self.prefix})"


def load_dataset(path: Union[str, Path, None] = None) -> dict:
    return json.loads(Path(path or _BUNDLED).read_text(encoding="utf-8"))


class Checker:
    """Longest-prefix match over every prefix in the dataset."""

    def __init__(self, dataset: dict):
        self.dataset = dataset
        self._nets = {4: [], 6: []}
        for rec in dataset["asns"]:
            for fam in ("ipv4", "ipv6"):
                for p in rec["prefixes"][fam]:
                    net = ipaddress.ip_network(p, strict=False)
                    self._nets[net.version].append((net, rec))
        for v in self._nets:  # most specific first, so the first hit wins
            self._nets[v].sort(key=lambda t: t[0].prefixlen, reverse=True)

    def lookup(self, ip: str) -> Result:
        addr = ipaddress.ip_address(str(ip).strip())
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        for net, rec in self._nets[addr.version]:
            if addr in net:
                return Result(
                    ip=str(addr), found=True, carrier=rec["carrier"],
                    carrier_name=CARRIER_NAMES.get(rec["carrier"], rec["carrier"]),
                    asn=rec["asn"], holder=rec["holder"], prefix=str(net), role=rec["role"],
                    is_mobile=rec["is_mobile"], confidence=rec["confidence"], evidence=list(rec["evidence"]),
                )
        return Result(ip=str(addr), found=False)


@lru_cache(maxsize=1)
def _default_checker() -> Checker:
    return Checker(load_dataset())


def lookup(ip: str) -> Result:
    """Classify one IP. Raises ValueError if ``ip`` is not an IP address."""
    return _default_checker().lookup(ip)
