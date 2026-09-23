import json
import subprocess
import sys

import pytest

from sg_ip_check import Checker, load_dataset, lookup
from sg_ip_check.cli import main as cli_main

TINY = {
    "asns": [
        {"asn": 1, "carrier": "singtel", "role": "carrier-core", "is_mobile": False, "confidence": "registry-name",
         "holder": "CORE", "evidence": ["core"], "prefixes": {"ipv4": ["10.0.0.0/8"], "ipv6": []}},
        {"asn": 2, "carrier": "singtel", "role": "mobile", "is_mobile": True, "confidence": "observed",
         "holder": "MOBILE", "evidence": ["seen"], "prefixes": {"ipv4": ["10.1.0.0/16"], "ipv6": ["2001:db8::/32"]}},
        {"asn": 3, "carrier": "simba", "role": "unknown", "is_mobile": None, "confidence": "uncertain",
         "holder": "SIMBA", "evidence": ["?"], "prefixes": {"ipv4": ["192.0.2.0/24"], "ipv6": []}},
    ]
}


def test_longest_prefix_wins():
    c = Checker(TINY)
    assert c.lookup("10.1.2.3").asn == 2          # inside the more-specific mobile /16
    assert c.lookup("10.1.2.3").is_mobile is True
    assert c.lookup("10.2.0.1").asn == 1          # only the covering /8 matches
    assert c.lookup("10.2.0.1").is_mobile is False


def test_unknown_role_is_none_not_false():
    r = Checker(TINY).lookup("192.0.2.9")
    assert r.found and r.is_mobile is None
    assert "unconfirmed" in r.summary


def test_not_found():
    r = Checker(TINY).lookup("203.0.113.1")
    assert not r.found and r.is_mobile is None and r.asn is None


def test_ipv6_and_ipv4_mapped():
    c = Checker(TINY)
    assert c.lookup("2001:db8::1").asn == 2
    assert c.lookup("::ffff:10.1.0.5").asn == 2


def test_invalid_ip_raises():
    with pytest.raises(ValueError):
        Checker(TINY).lookup("not-an-ip")


# --- the real bundled dataset ------------------------------------------------
# These are egress IPs we observed from real SIMs (see sources/asns.json).

@pytest.mark.parametrize("ip,carrier,asn", [
    ("119.234.8.104", "singtel", 45143),
    ("119.234.34.225", "singtel", 45143),
    ("119.56.16.102", "m1", 4773),
    ("119.56.17.42", "m1", 4773),
])
def test_bundled_observed_mobile_ips(ip, carrier, asn):
    r = lookup(ip)
    assert (r.carrier, r.asn, r.is_mobile, r.confidence) == (carrier, asn, True, "observed")


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_bundled_non_sg(ip):
    assert lookup(ip).found is False


def test_bundled_dataset_shape():
    ds = load_dataset()
    roles = {"mobile", "fixed-broadband", "carrier-core", "unknown"}
    for r in ds["asns"]:
        assert r["role"] in roles
        assert r["evidence"], f"AS{r['asn']} has no evidence"
        assert r["is_mobile"] == (True if r["role"] == "mobile" else None if r["role"] == "unknown" else False)


def test_bundled_copy_matches_data_dir():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert (root / "data" / "sg-asns.json").read_bytes() == \
        (root / "src" / "sg_ip_check" / "data" / "sg-asns.json").read_bytes()


def test_cli_json(capsys):
    assert cli_main(["119.56.16.102", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["carrier"] == "m1" and out["is_mobile"] is True


def test_cli_bad_ip(capsys):
    assert cli_main(["nope"]) == 2
