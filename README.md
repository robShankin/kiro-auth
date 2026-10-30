# kiro-auth

A small Python/bash helper that stops the daily kiro-cli browser re-login. It
reads the live token expiry and triggers a silent refresh via the SSO refresh
token, only prompting for a browser login when the org SSO session ceiling is
actually hit. Runs on macOS, Windows, and Linux.

## The short version

kiro-cli's access token is short-lived (~1h) but renews **silently** via the SSO
refresh token on any authed op — no browser. The daily browser login most people
suffer is self-inflicted: running `kiro-cli logout` then `login` discards the
refresh token and forces a browser login every time. Stop doing that, and let
this helper nudge a silent refresh when needed.

A browser login is genuinely required only when the **org SSO session ceiling**
expires. That step is interactive by design (OIDC + IdP + MFA) and cannot be
scripted away.

## Requirements

- Python 3.8+ (standard library only — no pip installs)
- `kiro-cli` installed and on your PATH
- You have logged into kiro-cli at least once (so a session exists to refresh)

## First-time setup

1. **Clone and enter the repo.**

   ```bash
   git clone <this-repo>
   cd kiro-auth
   ```

2. **Create your local config** (optional but recommended). This holds your
   org's SSO details and is git-ignored, so it never gets committed.

   ```bash
   cp kiro-auth.config.example kiro-auth.config
   ```

   Then edit `kiro-auth.config` and fill in your values. Find them by running:

   ```bash
   kiro-cli user whoami
   ```

   That prints your Identity Center start URL and region. Put those into:

   ```ini
   IDP_URL=https://your-org.awsapps.com/start
   REGION=your-region          # e.g. us-east-1
   LICENSE=pro                 # pro for Identity Center, free for Builder ID/social
   ```

   Alternatively, skip the file and export environment variables instead
   (these override the file):

   ```bash
   export KIRO_AUTH_IDP_URL=https://your-org.awsapps.com/start
   export KIRO_AUTH_REGION=your-region
   export KIRO_AUTH_LICENSE=pro
   ```

   > These values are used **only** in the browser-login fallback message, to
   > print the exact `kiro-cli login` command for your org. The script still
   > works without them — it just shows placeholders in that one message.

3. **(Optional) make it callable from anywhere** (macOS/Linux):

   ```bash
   ln -sf "$(pwd)/kiro-auth.py" ~/.local/bin/kiro-auth   # ensure ~/.local/bin is on PATH
   ```

## Usage

```bash
# macOS / Linux
python3 kiro-auth.py
./kiro-auth.sh

# Windows
python kiro-auth.py

# flags
-q, --quiet    print only when action is taken or on error
-h, --help     help
```

What it does each run:

1. Reads the live token expiry from kiro-cli's SQLite store (`auth_kv`). Only the
   expiry timestamp is read — never the token value.
2. Valid with margin → prints `OK: token valid...` and exits.
3. Expired/expiring → silent refresh via a one-shot `kiro-cli chat`. No browser.
4. Refresh failed (SSO ceiling hit) → prints the exact `logout` + `login`
   commands and exits non-zero. This is the only case needing a browser.

## Day-to-day

- **Don't run `kiro-cli logout` / `login` daily.** That discards the refresh
  token and forces the browser. Just use kiro-cli; it refreshes itself.
- Run this helper to proactively ensure freshness before a work session.
- You'll still hit the browser occasionally when your org SSO session ceiling
  expires — that's by design.

## Privacy / what's in the repo

- The scripts read only the token **expiry timestamp**, never the token value.
  No credentials are read, printed, or stored.
- No org identifiers are committed. Your SSO URL/region live only in your
  git-ignored `kiro-auth.config` or in environment variables.
- `.gitignore` also excludes `data.sqlite3`, `*token*.json`, `.DS_Store`, and
  editor directories.

## Known caveat: Windows DB path

The live-token DB location on Windows (`%LOCALAPPDATA%\kiro-cli\data.sqlite3`) is
a best guess, unconfirmed on a real Windows machine. If the script can't find the
DB it prints every path it tried — report that so the path can be pinned.
