# mastodon-search

A dependency-free CLI for searching a Mastodon instance's account index, with
result filtering that removes the false positives the API returns for
email-shaped queries.

Python 3.9+ standard library only. No `pip install` required.

## Why this exists

Two quirks of Mastodon's `/api/v2/search` endpoint make naive querying
misleading:

1. **`q` is a single opaque string.** Passing a comma-separated list of
   identifiers matches nothing, because the API searches for the literal
   comma-joined string rather than each term.
2. **`user@domain` queries fall back to matching the domain.** Mastodon parses
   an `@`-containing query as a fediverse handle. Searching for
   `someone@gmail.com` therefore returns every unrelated account with
   `gmail.com` in its display name — often dozens of them.

This script issues one request per identifier and discards results that match
only the domain portion, so a "no matches" answer is trustworthy.

## Requirements

Python 3.9 or newer. Nothing else — the script imports only the standard
library, so there is no virtualenv, `requirements.txt`, or install step.

macOS ships a suitable Python 3. Confirm yours:

```bash
python3 --version
```

If that reports an error or a version below 3.9, install a current Python with
`brew install python` (macOS), `apt install python3` (Debian/Ubuntu), or from
[python.org](https://www.python.org/downloads/).

## Installation

Clone the repository and mark the script executable:

```bash
git clone https://github.com/sunny-teamoperator/mastodon-search.git
cd mastodon-search
chmod +x mastodon_search.py
```

Verify it runs:

```bash
./mastodon_search.py --help
```

To call it from anywhere, symlink it onto your `PATH`:

```bash
ln -s "$PWD/mastodon_search.py" /usr/local/bin/mastodon-search
```

## Running

```bash
./mastodon_search.py TERM [TERM ...]
```

If you skipped `chmod`, or the shebang does not resolve on your system, invoke
the interpreter directly — this works identically:

```bash
python3 mastodon_search.py TERM [TERM ...]
```

A first run needs no configuration, though results are limited without a token
(see [Authentication](#authentication)):

```bash
./mastodon_search.py Gargron
```

Terms may be usernames or email addresses. Comma-separated values are split
automatically, so both of these are equivalent:

```bash
./mastodon_search.py alice bob carol@example.com
./mastodon_search.py "alice,bob,carol@example.com"
```

The script exits `0` on success and `2` when no usable search terms were given.
Per-term failures (HTTP, network, malformed JSON) are reported on stderr and do
not abort the remaining lookups.

### Options

| Flag | Description |
| --- | --- |
| `--instance HOST` | Instance to query (default: `mastodon.social`) |
| `--limit N` | Max accounts per term (default: 20; instances usually cap at 40) |
| `--resolve` | Ask the instance to fetch unknown remote accounts (requires auth) |
| `--token TOKEN` | OAuth token; defaults to `$MASTODON_TOKEN` |
| `--delay SECONDS` | Pause between requests (default: 0.5) |
| `--json` | Emit structured JSON instead of the text report |
| `--show-filtered` | List the accounts that were discarded as non-matching |
| `--no-filter` | Keep everything the API returns, including domain-only hits |

### Examples

Search a different instance:

```bash
./mastodon_search.py --instance fosstodon.org alice
```

Audit what the filter removed:

```bash
./mastodon_search.py --show-filtered carol@example.com
```

Machine-readable output:

```bash
./mastodon_search.py --json alice bob > results.json
```

Resolve remote accounts the instance hasn't seen yet:

```bash
export MASTODON_TOKEN="your_token"
./mastodon_search.py --resolve alice@remote.instance
```

## Authentication

Account search on most instances requires an OAuth token. Without one you will
typically receive `HTTP 401` or a reduced result set.

To obtain a token on mastodon.social: **Preferences → Development → New
application**, grant the `read:search` and `read:accounts` scopes, then copy the
access token.

```bash
export MASTODON_TOKEN="your_token_here"
```

Add it to `~/.zshrc` to persist it. The token is only ever sent as an
`Authorization: Bearer` header to the instance you specify.

## How filtering works

An account survives the filter when either condition holds:

- The **complete search term** appears in its profile text — username, handle,
  display name, profile URL, bio, or custom fields (HTML stripped first).
- For email terms, the **local part** equals its username or handle, so
  `alice@example.com` still matches the account `@alice`.

Domain-only matches fail both checks. Use `--show-filtered` to review the
discards, or `--no-filter` to bypass filtering entirely.

## Output

The default text report prints, per term, each matching account's handle, ID,
display name, URL, follower/following/post counts, creation and last-post
dates, bot/locked flags, bio, and profile fields. A trailing line reports the
unique account total and how many results were discarded.

`--json` emits the same data as structured output with these keys:
`instance`, `terms`, `filter_applied`, `total_filtered_out`, `unique_accounts`,
`by_term`, and `filtered_out_by_term`.

## Limitations

- **Instances only search what they know.** A server can search accounts it has
  encountered through federation, not the whole fediverse. A zero result means
  "absent from this instance's index," not "does not exist." Query the person's
  home instance directly for a conclusive answer.
- **Registration emails are never exposed.** No Mastodon API surfaces the email
  someone signed up with. Email terms only match when a user has published that
  address in their own display name or bio.
- **Anonymous searches are degraded.** Expect fewer results without a token.
- **Rate limits apply.** Roughly 300 requests per 5 minutes per instance;
  increase `--delay` for large term lists.

## License

[MIT](LICENSE)
