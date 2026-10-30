#!/usr/bin/env bash
#
# kiro-auth — keep kiro-cli IAM Identity Center auth fresh with zero clicks.
#
# Key facts (discovered by inspecting a live install):
#   - The LIVE token lives in kiro-cli's SQLite at auth_kv -> "kirocli:odic:token",
#     NOT in ~/.aws/sso/cache/*.json (that file is a stale export).
#   - The access token is short-lived (~1h) but renews SILENTLY via the refresh
#     token whenever an authed op runs. No browser, no logout needed.
#   - `kiro-cli login` REFUSES while a session exists ("Already logged in").
#     So a logout->login habit forces the daily browser prompt: logout throws
#     away the refresh token, guaranteeing a browser login.
#
# What this does:
#   - If the live token is valid with margin -> nothing.
#   - If expired/expiring -> trigger a SILENT refresh via a one-shot
#     `kiro-cli chat --no-interactive` (uses the refresh token; no browser).
#   - Only if that fails (refresh token truly dead) does it tell you to
#     logout + login — the one case a browser click is unavoidable.
#
# Configuration (for the fallback login hint only; NOT committed):
#   Reads KIRO_AUTH_IDP_URL / KIRO_AUTH_REGION / KIRO_AUTH_LICENSE from the
#   environment, else from a local git-ignored `kiro-auth.config` beside this
#   script. Copy kiro-auth.config.example to kiro-auth.config and fill in yours.
#
# Usage:
#   ./kiro-auth.sh        # check + silent refresh if needed
#   ./kiro-auth.sh -q     # quiet unless action/error
#   ./kiro-auth.sh -h     # help
#
set -euo pipefail

MARGIN_SECONDS=300   # refresh if token dies within 5 min
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

QUIET=0
for arg in "$@"; do
  case "$arg" in
    -q|--quiet) QUIET=1 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
say() { [ "$QUIET" -eq 1 ] || echo "$@"; }

# --- load optional local config (git-ignored), then env vars override --------
IDP_URL=""; REGION=""; LICENSE="pro"
if [ -f "$HERE/kiro-auth.config" ]; then
  # shellcheck disable=SC1090
  while IFS='=' read -r k v; do
    k="$(echo "$k" | tr -d '[:space:]')"
    v="$(echo "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//')"
    case "$k" in
      IDP_URL) IDP_URL="$v" ;;
      REGION) REGION="$v" ;;
      LICENSE) LICENSE="$v" ;;
    esac
  done < <(grep -vE '^[[:space:]]*#' "$HERE/kiro-auth.config" | grep '=')
fi
IDP_URL="${KIRO_AUTH_IDP_URL:-$IDP_URL}"
REGION="${KIRO_AUTH_REGION:-$REGION}"
LICENSE="${KIRO_AUTH_LICENSE:-$LICENSE}"

# --- locate kiro-cli's SQLite store across OSes ------------------------------
find_db() {
  local candidates=()
  case "$(uname -s)" in
    Darwin) candidates+=("$HOME/Library/Application Support/kiro-cli/data.sqlite3") ;;
    *)      candidates+=("${XDG_DATA_HOME:-$HOME/.local/share}/kiro-cli/data.sqlite3") ;;
  esac
  candidates+=("$HOME/.local/share/kiro-cli/data.sqlite3")
  for p in "${candidates[@]}"; do
    [ -f "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}

DB="$(find_db || true)"
if [ -z "$DB" ]; then
  say "ERROR: could not locate kiro-cli's data.sqlite3."
  say "If kiro-cli is installed, log in once: kiro-cli login --license ${LICENSE:-pro}"
  exit 1
fi

# Read live token expiry from auth_kv (seconds remaining; no secrets printed).
remaining="$(python3 - "$DB" <<'PY'
import sqlite3, sys, json, datetime
try:
    c = sqlite3.connect(sys.argv[1])
    row = c.execute("select value from auth_kv where key='kirocli:odic:token'").fetchone()
    d = json.loads(row[0])
    exp = d.get("expires_at") or d.get("expiresAt")
    e = datetime.datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    print(int((e - now).total_seconds()))
except Exception:
    print("ERR")
PY
)"

silent_refresh() {
  say "-> Nudging a silent refresh (no browser)..."
  # A trivial one-shot authed op forces the refresh-token renewal.
  if kiro-cli chat --no-interactive --trust-tools= "ok" >/dev/null 2>&1; then
    say "OK: token refreshed silently."
    return 0
  fi
  return 1
}

if [ "$remaining" != "ERR" ] && [ "$remaining" -gt "$MARGIN_SECONDS" ]; then
  say "OK: token valid for ~$(( remaining / 60 )) min. No action needed."
  exit 0
fi

say "Token expired or expiring soon."
if silent_refresh; then
  exit 0
fi

# Refresh token is dead -- the only case that needs the browser.
idp="${IDP_URL:-<your-sso-start-url>}"
region="${REGION:-<your-region>}"
hint=""
if [ -z "$IDP_URL" ] || [ -z "$REGION" ]; then
  hint="
(Set your IdP/region in kiro-auth.config or KIRO_AUTH_* env vars so this
message shows your real values -- see README.)"
fi
cat >&2 <<EOF
FAILED: silent refresh did not work -- your SSO refresh token has expired.
  This is the one case that needs a browser. Run:

    kiro-cli logout
    kiro-cli login --license ${LICENSE:-pro} \\
      --identity-provider ${idp} \\
      --region ${region}${hint}
EOF
exit 1
