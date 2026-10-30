# kiro-cli auth: notes & design log

_Last updated: 2026-10-30_

Background and reasoning behind the helper scripts. For install/usage see
`README.md`.

## The problem

Daily friction: having to re-auth into kiro-cli via the command line **and**
click through the AWS SSO browser login every day. Goal: script that away.

## What we found (the root cause)

The daily browser login was **mostly self-inflicted by the routine**, not a real
expiry problem.

Two independent clocks:

1. **Access token (~1h, short-lived).** Renews **silently** via the refresh
   token whenever any authed op runs (e.g. `kiro-cli chat`). No browser, no
   logout. Verified: a one-shot `kiro-cli chat` succeeded against an "expired"
   cached token with no browser prompt.
2. **Refresh token / SSO session (the real ceiling).** Longer-lived but finite,
   capped by the org's IAM Identity Center config. When this dies, a browser
   login is **unavoidable** — interactive OIDC + IdP sign-in (typically with
   MFA), a human-presence check. Not scriptable, by design.

**The trap:** `kiro-cli login` refuses to run while a session exists
(`error: Already logged in, please logout with kiro-cli logout first`). So the
habit of `logout` → `login` each morning **destroys the refresh token**, which
forces the browser every time. Dropping that habit removes the daily pain.

### Where the live token actually lives

- Live token: kiro-cli's SQLite DB, table `auth_kv`, key `kirocli:odic:token`.
  - macOS: `~/Library/Application Support/kiro-cli/data.sqlite3`
  - Windows (best guess, unconfirmed): `%LOCALAPPDATA%\kiro-cli\data.sqlite3`
  - Linux: `~/.local/share/kiro-cli/data.sqlite3`
- `~/.aws/sso/cache/*.json` (incl. `kiro-auth-token.json`) is a **stale export** —
  do NOT read expiry from it. The first version of the script did and was wrong.
- The scripts read only the token's **expiry timestamp**, never the token value.

## The "no-browser AWS refresh" question (a tangent worth recording)

A common pattern people remember as "browser-free AWS auth" is a two-step shell
shortcut like:

1. `aws sso login --profile <profile>`          ← this IS still a browser login
2. `aws rds generate-db-auth-token ... | pbcopy` ← local-only, no browser

The browser-free feeling comes from step 2: `generate-db-auth-token` is pure
local signing math off already-established credentials. It is the RDS analog of
kiro-cli's silent refresh — both skip the browser **only because a prior
interactive login seeded the session**. There is **no kiro-cli equivalent** that
mints a brand-new SSO authorization without the browser. Conclusion: that pattern
contains no bypass, just a browser login plus a local-only token mint.

## The solution

Two helper scripts that:
- Read the live token expiry from `auth_kv`.
- If valid (with a 5-min margin) → do nothing.
- If expired/expiring → trigger a **silent refresh** via one-shot
  `kiro-cli chat --no-interactive` (uses refresh token, no browser).
- If that fails (refresh token truly dead) → print the exact `logout` + `login`
  commands and exit non-zero. The only case needing a browser.

Fail-safe note: "refresh failed" is inferred from `kiro-cli chat` returning
non-zero. A non-zero for an unrelated reason (network blip) also lands here and
tells you to log in — harmless (one extra browser click), never leaves you stuck.

### Files

- `README.md` — front door: what it is, first-time setup, usage, caveats.
- `kiro-auth.sh` — bash + python3. macOS/Linux.
- `kiro-auth.py` — portable Python 3.8+ (stdlib only). macOS/Windows/Linux. The
  shareable version.
- `kiro-auth.config.example` — template for org-specific values; copy to
  `kiro-auth.config` (git-ignored).
- `.gitignore` — excludes .DS_Store, editor dirs, the real config, and any
  token/credential files.
- `KIRO-AUTH-NOTES.md` — this doc.

### Configuration is externalized

Org-specific values (SSO start URL, region, license) are **not** hardcoded. They
load from `KIRO_AUTH_*` env vars, else a git-ignored `kiro-auth.config`, else
blank placeholders. This keeps the repo free of any org identifiers. The values
are used only in the browser-login fallback message. See README "First-time
setup".

## Day-to-day guidance

- **Stop running `kiro-cli logout` / `login` daily.** Just use kiro-cli; it
  refreshes itself.
- Run the helper when you want to proactively ensure freshness before a session.
- You'll still hit the browser occasionally when the **org SSO session ceiling**
  expires. That part is by design and not scriptable.

## Outstanding / TODO

- [ ] **Confirm the Windows DB path.** `%LOCALAPPDATA%\kiro-cli\data.sqlite3` is
      a guess. First Windows user to run `kiro-auth.py`: if it can't find the DB
      it prints every path it tried — report that back so the path can be pinned.
- [ ] Optional: verify the real SSO session ceiling length (how often the browser
      is genuinely required) and, if too short, ask AWS admins to extend the
      Identity Center session duration.
- [x] Swap Unicode status markers for plain ASCII (`OK:`/`FAILED:`) — garbled in
      transit/other fonts. Done 2026-10-30.
- [x] Externalize org/personal specifics into a git-ignored config + template so
      the repo is safe to share. Done 2026-10-30.
