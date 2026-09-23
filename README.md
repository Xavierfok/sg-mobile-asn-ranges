# sg-mobile-asn-ranges

Which IP ranges belong to Singapore's mobile networks, and how sure can you be?

This repo lists the ASNs of Singtel, M1, StarHub and Simba, the IPv4 and IPv6
prefixes each one announces, and a role for each ASN (mobile, fixed broadband,
carrier core or unknown). Every role comes with the evidence behind it. The
prefixes are refreshed weekly from public BGP data.

It also ships `sg-ip-check`, a small offline Python library and CLI that
answers "is this a Singapore mobile IP?" for a single address.

## The ASNs

| ASN | Carrier | Role | Confidence | Why |
|---|---|---|---|---|
| AS45143 | Singtel | mobile | observed | Registry name `SINGTELMOBILE-AS-AP`; real Singtel SIMs egressed from it (2026-08-26) |
| AS7473 | Singtel | carrier core | registry name | `SINGTEL-AS-AP`, Singtel's main ASN. Our Singtel SIMs did **not** exit here |
| AS3758 | Singtel | fixed broadband | registry name | `SINGNET` |
| AS9506 | Singtel | fixed broadband | registry name | `SINGTEL-FIBRE` |
| AS4773 | M1 | mobile | observed | Registry name `MOBILEONELTD-AS-AP`; real M1 SIMs egressed from it (2026-09-02) |
| AS17547 | M1 | carrier core | registry name | `M1NET-SG-AP`. Often quoted as "the M1 ASN", but our M1 SIMs did **not** exit here |
| AS132915 | M1 | fixed broadband | registry name | `MOBILEONELTD-AS-NGNBN` (national fibre network) |
| AS138345 | StarHub | mobile | registry name | `STARHUB-MOBILE2`, APNIC descr "StarHub Mobile2". Not confirmed with a live SIM |
| AS9874 | StarHub | mobile | registry name | `STARHUB-MOBILE`, currently announces nothing. Kept so old references resolve |
| AS4657 | StarHub | carrier core | registry name | `STARHUB-INTERNET` |
| AS55430 | StarHub | fixed broadband | registry name | `STARHUB-NGNBN` (national fibre network) |
| AS4817 | Simba | unknown | uncertain | `STPL-SG-AP`, Simba Telecom. Simba runs a mobile network, but nothing public says this ASN carries its subscribers |

**Confidence levels.** `observed` means we watched traffic from real SIMs on that
network leave through that ASN. `registry-name` means the RIR/whois record
names the ASN's purpose and we are taking it at its word. `uncertain` means
we could not tell, so `is_mobile` is `null` rather than a guess.

The full evidence strings are in [`sources/asns.json`](sources/asns.json), and
they are copied into every record in `data/sg-asns.json`.

## Files

| File | What's in it |
|---|---|
| `data/sg-asns.json` | Everything: one record per ASN with role, confidence, evidence, holder name and prefixes |
| `data/sg-prefixes.csv` | One row per prefix: `prefix,family,asn,carrier,role,confidence,holder` |
| `data/cidr/all-mobile-ipv4.txt` / `all-mobile-ipv6.txt` | Every prefix from a `mobile` ASN, one per line |
| `data/cidr/<carrier>-mobile.txt` | Mobile prefixes for one carrier (`singtel`, `m1`, `starhub`) |
| `data/cidr/<carrier>.txt` | Every prefix for one carrier, all roles |

Raw URLs work straight from GitHub, e.g.
`https://raw.githubusercontent.com/Xavierfok/sg-mobile-asn-ranges/main/data/cidr/all-mobile-ipv4.txt`.

## Usage

### Python (`sg-ip-check`)

```bash
pip install git+https://github.com/Xavierfok/sg-mobile-asn-ranges
sg-ip-check 119.234.8.104 8.8.8.8
# 119.234.8.104 is a Singapore mobile IP (Singtel, AS45143, 119.234.8.0/24)
# 8.8.8.8 is not in any Singapore carrier range this dataset tracks
sg-ip-check --me --json
```

```python
from sg_ip_check import lookup

r = lookup("119.56.16.102")
r.is_mobile      # True
r.carrier_name   # 'M1'
r.asn            # 4773
r.confidence     # 'observed'
r.evidence       # why we think so
```

`is_mobile` is `True`, `False` or `None`. `None` means either the IP isn't in
any range we track, or it is in an ASN whose role we could not confirm. Check
`r.found` to tell those two apart. The lookup is offline because the dataset
ships inside the package.

### JavaScript

```js
const res = await fetch(
  "https://raw.githubusercontent.com/Xavierfok/sg-mobile-asn-ranges/main/data/cidr/all-mobile-ipv4.txt");
const cidrs = (await res.text()).trim().split("\n");

const toInt = ip => ip.split(".").reduce((n, o) => (n << 8) + Number(o), 0) >>> 0;
const inCidr = (ip, cidr) => {
  const [base, bits] = cidr.split("/");
  const mask = bits === "0" ? 0 : (~0 << (32 - Number(bits))) >>> 0;
  return (toInt(ip) & mask) === (toInt(base) & mask);
};

const isSgMobile = ip => cidrs.some(c => inCidr(ip, c));
isSgMobile("119.234.8.104"); // true
```

### nftables

```bash
curl -s https://raw.githubusercontent.com/Xavierfok/sg-mobile-asn-ranges/main/data/cidr/all-mobile-ipv4.txt \
  | paste -sd, - \
  | xargs -I{} nft add element inet filter sg_mobile_v4 '{ {} }'
```

with a set created once as
`nft add set inet filter sg_mobile_v4 '{ type ipv4_addr; flags interval; auto-merge; }'`.

## How the lookup decides

Routes overlap. StarHub, for example, announces 173 more-specific mobile
routes from AS138345 inside larger blocks announced by AS4657. The lookup uses
**longest-prefix match**, the same rule routers use, so an address takes the
role of the most specific prefix that contains it.

## Limitations (please read before blocking anyone)

- **The role is per ASN, not per prefix.** If a carrier routes some mobile
  subscribers out of an ASN we list as carrier core, those addresses will
  show as non-mobile. Only the Singtel and M1 mobile ASNs are confirmed with
  real SIMs.
- **This is announced BGP data, not geolocation.** A Singtel prefix is
  registered to Singtel, but that does not prove the device is in Singapore:
  roaming and enterprise links exist.
- **CGNAT is normal on mobile networks.** Mobile carriers commonly put many
  subscribers behind one public IPv4 address (carrier-grade NAT, with the
  internal side often in `100.64.0.0/10`, RFC 6598). So one mobile IP can be
  hundreds of real people, and blocking a mobile /24 can lock out a lot of
  them. We have not measured how many subscribers share an address on each
  carrier.
- **MVNOs don't have their own ranges here.** Virtual operators ride on a host
  network and exit through its ASNs. We have observed Circles.Life SIMs exit
  through M1 (AS4773). We have not verified other MVNOs.
- **Refresh lag.** Prefixes are re-pulled weekly. A guard refuses to write if
  the total drops by more than 25% or an ASN suddenly goes empty, which
  usually means the data source hiccupped.

Corrections are very welcome: open an issue with the IP, what you expected,
and how you know (a traceroute, a SIM you own, a registry record).

## Regenerating

```bash
python scripts/generate.py          # pulls RIPEstat, rewrites data/ only if something changed
python scripts/generate.py --force  # write even if the sanity guard objects
pytest -q
```

To add or reclassify an ASN, edit `sources/asns.json` with the evidence and
rerun. The generator never changes a role on its own.

## Who made this

It was built while running [Singapore Mobile Proxy](https://singaporemobileproxy.com/?utm_source=github&utm_medium=repo&utm_campaign=sg-mobile-asn-ranges),
which sells real Singtel and M1 mobile IPs, because we kept needing to answer
"does this IP really look like a Singapore phone?"

## Licence

Code: MIT ([`LICENSE`](LICENSE)). Data: CC BY 4.0 ([`LICENSE-DATA.md`](LICENSE-DATA.md)),
with prefix and registry data courtesy of the RIPE NCC's RIPEstat.
