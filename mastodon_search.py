#!/usr/bin/env python3
"""Search a Mastodon instance for accounts and print a parsed summary.

Mastodon's /api/v2/search endpoint treats `q` as a single query string, so a
comma-separated list of usernames/emails matches nothing. This script splits
the terms and issues one request per term, then merges the results.

Results are filtered so that only accounts matching the *whole* term survive.
Mastodon parses a `user@domain` query as a handle and returns accounts that
share only the domain, so an email search otherwise floods you with unrelated
`*@gmail.com` display names.

Usage:
    ./mastodon_search.py alice bob carol@example.com
    ./mastodon_search.py "alice,bob,carol@example.com"
    ./mastodon_search.py --json alice > results.json
    ./mastodon_search.py --instance mastodon.online alice
    ./mastodon_search.py --show-filtered carol@example.com
    ./mastodon_search.py --no-filter carol@example.com

Auth:
    Account search on most instances requires an OAuth token. Set one via:
        export MASTODON_TOKEN="..."
    Without it you will typically get HTTP 401 or empty results.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any, Iterable

DEFAULT_INSTANCE = "mastodon.social"
USER_AGENT = "mastodon-search-script/1.0 (+stdlib urllib)"
TAG_RE = re.compile(r"<[^>]+>")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("terms", nargs="+",
                        help="Search terms (usernames or emails). Comma-separated values are split.")
    parser.add_argument("--instance", default=DEFAULT_INSTANCE,
                        help=f"Mastodon instance hostname (default: {DEFAULT_INSTANCE})")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max accounts per term (default: 20, instance max is usually 40)")
    parser.add_argument("--resolve", action="store_true",
                        help="Ask the instance to resolve remote accounts (requires auth)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit merged raw JSON instead of a human-readable table")
    parser.add_argument("--no-filter", action="store_true",
                        help="Keep every account the API returns, including domain-only matches")
    parser.add_argument("--show-filtered", action="store_true",
                        help="List the accounts that were discarded as non-matches")
    parser.add_argument("--token", default=os.environ.get("MASTODON_TOKEN"),
                        help="OAuth token (defaults to $MASTODON_TOKEN)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds to sleep between requests (default: 0.5)")
    return parser.parse_args(argv)


def expand_terms(raw_terms: Iterable[str]) -> list[str]:
    """Split comma-separated groups and drop blanks/duplicates, preserving order."""
    seen: set[str] = set()
    terms: list[str] = []
    for raw in raw_terms:
        for term in raw.split(","):
            term = term.strip()
            if term and term.lower() not in seen:
                seen.add(term.lower())
                terms.append(term)
    return terms


def search_accounts(instance: str, term: str, *, limit: int, resolve: bool,
                    token: str | None) -> list[dict[str, Any]]:
    """Call /api/v2/search for one term and return the `accounts` list."""
    query = urllib.parse.urlencode({
        "q": term,
        "type": "accounts",
        "limit": limit,
        "resolve": "true" if resolve else "false",
    })
    url = f"https://{instance}/api/v2/search?{query}"

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        print(f"  ! HTTP {exc.code} for {term!r}: {detail[:200]}", file=sys.stderr)
        if exc.code == 401:
            print("    (account search usually requires $MASTODON_TOKEN)", file=sys.stderr)
        return []
    except urllib.error.URLError as exc:
        print(f"  ! Network error for {term!r}: {exc.reason}", file=sys.stderr)
        return []
    except json.JSONDecodeError as exc:
        print(f"  ! Invalid JSON for {term!r}: {exc}", file=sys.stderr)
        return []

    return payload.get("accounts", [])


def strip_html(value: str) -> str:
    """Turn a profile note's HTML into a single line of plain text."""
    text = unescape(TAG_RE.sub(" ", value or ""))
    return " ".join(text.split())


def account_haystack(account: dict[str, Any]) -> str:
    """Every piece of searchable profile text, lowercased into one string."""
    parts = [
        account.get("username") or "",
        account.get("acct") or "",
        account.get("display_name") or "",
        account.get("url") or "",
        strip_html(account.get("note", "")),
    ]
    for field in account.get("fields", []):
        parts.append(field.get("name") or "")
        parts.append(strip_html(field.get("value", "")))
    return " ".join(parts).lower()


def matches_term(account: dict[str, Any], term: str) -> bool:
    """True only if the account matches the full term, not merely an email domain.

    An account is kept when either:
      * the complete term appears somewhere in its profile text, or
      * the local part of an email term equals its username or acct handle
        (so `alice@example.com` still matches the account `@alice`).
    """
    term = term.strip().lower()
    if not term:
        return False

    if term in account_haystack(account):
        return True

    if "@" not in term:
        return False

    local = term.partition("@")[0]
    if not local:
        return False

    username = (account.get("username") or "").lower()
    acct_local = (account.get("acct") or "").lower().partition("@")[0]
    return local in (username, acct_local)


def summarize(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account.get("id"),
        "acct": account.get("acct"),
        "display_name": account.get("display_name"),
        "url": account.get("url"),
        "created_at": account.get("created_at"),
        "last_status_at": account.get("last_status_at"),
        "followers": account.get("followers_count"),
        "following": account.get("following_count"),
        "statuses": account.get("statuses_count"),
        "bot": account.get("bot"),
        "locked": account.get("locked"),
        "note": strip_html(account.get("note", "")),
        "fields": [
            {"name": f.get("name"), "value": strip_html(f.get("value", "")),
             "verified_at": f.get("verified_at")}
            for f in account.get("fields", [])
        ],
    }


def print_account(index: int, account: dict[str, Any]) -> None:
    info = summarize(account)
    print(f"  {index}. @{info['acct']}  (id {info['id']})")
    if info["display_name"]:
        print(f"       name:      {info['display_name']}")
    print(f"       url:       {info['url']}")
    print(f"       stats:     {info['followers']} followers / "
          f"{info['following']} following / {info['statuses']} posts")
    print(f"       created:   {info['created_at']}   last post: {info['last_status_at']}")
    flags = [k for k in ("bot", "locked") if info[k]]
    if flags:
        print(f"       flags:     {', '.join(flags)}")
    if info["note"]:
        note = info["note"]
        print(f"       bio:       {note[:160] + '...' if len(note) > 160 else note}")
    for field in info["fields"]:
        verified = " [verified]" if field["verified_at"] else ""
        print(f"       {field['name']}: {field['value']}{verified}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    terms = expand_terms(args.terms)
    if not terms:
        print("No usable search terms provided.", file=sys.stderr)
        return 2

    if not args.token:
        print("Warning: no token set ($MASTODON_TOKEN); account search may return 401.",
              file=sys.stderr)

    merged: dict[str, dict[str, Any]] = {}
    matches_by_term: dict[str, list[dict[str, Any]]] = {}
    filtered_by_term: dict[str, list[dict[str, Any]]] = {}

    for position, term in enumerate(terms):
        if position and args.delay:
            time.sleep(args.delay)
        accounts = search_accounts(args.instance, term, limit=args.limit,
                                   resolve=args.resolve, token=args.token)

        kept: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        for account in accounts:
            if args.no_filter or matches_term(account, term):
                kept.append(account)
            else:
                dropped.append(account)

        matches_by_term[term] = kept
        filtered_by_term[term] = dropped
        for account in kept:
            key = account.get("acct") or str(account.get("id"))
            merged.setdefault(key, account)

    total_filtered = sum(len(v) for v in filtered_by_term.values())

    if args.as_json:
        print(json.dumps({
            "instance": args.instance,
            "terms": terms,
            "filter_applied": not args.no_filter,
            "total_filtered_out": total_filtered,
            "unique_accounts": [summarize(a) for a in merged.values()],
            "by_term": {t: [summarize(a) for a in accts]
                        for t, accts in matches_by_term.items()},
            "filtered_out_by_term": {t: [summarize(a) for a in accts]
                                     for t, accts in filtered_by_term.items()},
        }, indent=2, ensure_ascii=False))
        return 0

    for term in terms:
        accounts = matches_by_term[term]
        dropped = filtered_by_term[term]
        suffix = f"  [{len(dropped)} discarded as non-matching]" if dropped else ""
        print(f"\n{term} — {len(accounts)} match(es){suffix}")
        if not accounts:
            print("  (no accounts found)")
        for index, account in enumerate(accounts, start=1):
            print_account(index, account)
        if dropped and args.show_filtered:
            print("  discarded:")
            for account in dropped:
                print(f"       - @{account.get('acct')} "
                      f"({account.get('display_name') or 'no display name'})")

    print(f"\nTotal unique accounts across all terms: {len(merged)}")
    if total_filtered:
        note = "" if args.show_filtered else " (use --show-filtered to list them)"
        print(f"Discarded {total_filtered} domain-only/non-matching result(s){note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
