import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("generate", ROOT / "scripts" / "generate.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

SOURCES = {"asns": [
    {"asn": 100, "carrier": "singtel", "role": "mobile", "confidence": "observed", "evidence": ["x"]},
    {"asn": 200, "carrier": "m1", "role": "carrier-core", "confidence": "registry-name", "evidence": ["y"]},
]}


def fake_fetch(prefixes_by_asn):
    def fetch(url):
        asn = int(url.split("resource=AS")[1].split("&")[0])
        if "as-overview" in url:
            return {"data": {"holder": f"HOLDER-{asn}", "announced": bool(prefixes_by_asn.get(asn))}}
        return {"data": {"prefixes": [{"prefix": p} for p in prefixes_by_asn.get(asn, [])]}}
    return fetch


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "asns.json").write_text(json.dumps(SOURCES))
    return tmp_path


def run(repo, prefixes, *args):
    return gen.main(list(args), fetch=fake_fetch(prefixes), root=repo)


def test_writes_all_outputs(repo):
    assert run(repo, {100: ["1.2.3.0/24", "2001:db8::/32"], 200: ["5.6.0.0/16"]}) == 0
    ds = json.loads((repo / "data" / "sg-asns.json").read_text())
    assert [r["asn"] for r in ds["asns"]] == [200, 100]  # sorted by carrier then asn
    assert (repo / "data" / "cidr" / "singtel-mobile.txt").read_text() == "1.2.3.0/24\n2001:db8::/32\n"
    assert (repo / "data" / "cidr" / "all-mobile-ipv4.txt").read_text() == "1.2.3.0/24\n"
    assert not (repo / "data" / "cidr" / "m1-mobile.txt").exists()
    assert "5.6.0.0/16,ipv4,200,m1,carrier-core" in (repo / "data" / "sg-prefixes.csv").read_text()
    assert (repo / "src" / "sg_ip_check" / "data" / "sg-asns.json").exists()


def test_unchanged_run_rewrites_nothing(repo):
    p = {100: ["1.2.3.0/24"], 200: ["5.6.0.0/16"]}
    run(repo, p)
    f = repo / "data" / "sg-asns.json"
    before = f.read_bytes()
    assert run(repo, p) == 0
    assert f.read_bytes() == before  # generated_at not bumped either


def test_guard_blocks_big_drop(repo):
    run(repo, {100: [f"10.{i}.0.0/16" for i in range(20)], 200: ["5.6.0.0/16"]})
    before = (repo / "data" / "sg-asns.json").read_bytes()
    assert run(repo, {100: ["10.0.0.0/16"], 200: ["5.6.0.0/16"]}) == 2
    assert (repo / "data" / "sg-asns.json").read_bytes() == before
    assert run(repo, {100: ["10.0.0.0/16"], 200: ["5.6.0.0/16"]}, "--force") == 0


def test_guard_blocks_asn_going_empty(repo):
    run(repo, {100: ["1.2.3.0/24"] , 200: [f"5.{i}.0.0/16" for i in range(10)]})
    assert run(repo, {100: [], 200: [f"5.{i}.0.0/16" for i in range(10)]}) == 2


def test_prefixes_normalised_and_deduped(repo):
    run(repo, {100: ["1.2.3.4/24", "1.2.3.0/24"], 200: []})
    ds = json.loads((repo / "data" / "sg-asns.json").read_text())
    mob = [r for r in ds["asns"] if r["asn"] == 100][0]
    assert mob["prefixes"]["ipv4"] == ["1.2.3.0/24"]
