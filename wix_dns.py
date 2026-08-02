#!/usr/bin/env python3
"""Point a Wix-registered domain at this GitHub Pages site.

Reads everything from the environment so no secret or domain is ever hard-coded:

    WIX_API_KEY      account-level API key (Wix dashboard -> Settings -> API Keys)
    WIX_ACCOUNT_ID   shown on the same API Keys page
    GOLF_DOMAIN      the domain, bare - no https://, no www

Usage:
    python wix_dns.py            # dry run: show the zone and the planned change
    python wix_dns.py --apply    # actually write the records

Only the apex A record and the www CNAME are touched. MX, TXT and everything
else in the zone is left exactly as it is, so email on the domain keeps working.
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://www.wixapis.com/domains/v1/dns-zones"
TTL = 3600

# GitHub Pages apex servers - https://docs.github.com/pages/configuring-a-custom-domain
PAGES_IPS = [
    "185.199.108.153",
    "185.199.109.153",
    "185.199.110.153",
    "185.199.111.153",
]
PAGES_HOST = "jmflynch.github.io"


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"Missing {name}. Set it first - see the header of this file.")
    return v


def call(method, domain, key, account, body=None):
    req = urllib.request.Request(
        f"{API}/{domain}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": key,
            "wix-account-id": account,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        # never echo the key, even if it ends up in an error string
        sys.exit(f"Wix API {e.code} on {method}:\n{detail.replace(key, '<REDACTED>')}")


def show(records):
    if not records:
        print("  (zone is empty)")
    for r in sorted(records, key=lambda x: (x.get("type", ""), x.get("hostName", ""))):
        vals = r.get("values")
        vals = vals if isinstance(vals, list) else [vals]
        print(f"  {r.get('type','?'):<6} {r.get('hostName','?'):<34} {', '.join(map(str, vals))}")


def main():
    key, account, domain = env("WIX_API_KEY"), env("WIX_ACCOUNT_ID"), env("GOLF_DOMAIN")
    domain = domain.lower().removeprefix("https://").removeprefix("http://").strip("/")
    if domain.startswith("www."):
        domain = domain[4:]
    apply = "--apply" in sys.argv
    www = f"www.{domain}"

    zone = call("GET", domain, key, account).get("dnsZone", {})
    records = zone.get("records", [])
    print(f"\nCurrent zone ({len(records)} records):")
    show(records)

    # The API allows one record object per type+host, so an existing apex A
    # record or www CNAME has to be deleted before the new one is added.
    deletions = [
        r for r in records
        if (r.get("type") == "A" and r.get("hostName") in (domain, "@"))
        or (r.get("type") == "CNAME" and r.get("hostName") == www)
    ]
    additions = [
        {"type": "A", "hostName": domain, "ttl": TTL, "values": PAGES_IPS},
        {"type": "CNAME", "hostName": www, "ttl": TTL, "values": [PAGES_HOST]},
    ]

    print("\nPlanned change:")
    if deletions:
        print("  remove:")
        show(deletions)
    else:
        print("  remove: nothing")
    print("  add:")
    show(additions)

    kept = [r for r in records if r not in deletions]
    mx = [r for r in kept if r.get("type") in ("MX", "TXT", "SPF")]
    if mx:
        print(f"\n  {len(mx)} MX/TXT/SPF record(s) left untouched - email keeps working.")

    if not apply:
        print("\nDry run. Nothing was changed. Re-run with --apply to write it.")
        return

    body = {"domainName": domain, "additions": additions}
    if deletions:
        body["deletions"] = deletions
    result = call("PATCH", domain, key, account, body).get("dnsZone", {})
    print("\nDone. Zone is now:")
    show(result.get("records", []))
    print("\nNext: set the custom domain at")
    print("  https://github.com/jmflynch/golf-tour/settings/pages")
    print("then tick Enforce HTTPS once the certificate is issued.")


if __name__ == "__main__":
    main()
