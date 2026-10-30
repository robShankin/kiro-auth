#!/usr/bin/env python3
"""
kiro-auth — keep kiro-cli (IAM Identity Center) auth fresh with zero clicks.

Cross-platform: runs on macOS, Windows, and Linux with the same file.
Requires only Python 3.8+ (standard library) and the `kiro-cli` executable.

How kiro-cli auth actually works (discovered by inspecting a live install):
  - The LIVE token lives in kiro-cli's SQLite DB, table `auth_kv`,
    key "kirocli:odic:token" — NOT in ~/.aws/sso/cache/*.json (stale export).
  - The access token is short-lived (~1h) but renews SILENTLY via the refresh
    token whenever an authed op runs. No browser, no logout required.
  - `kiro-cli login` REFUSES while a session exists ("Already logged in").
    So a logout->login habit is what forces the daily browser prompt: logout
    discards the refresh token, guaranteeing a browser login next time.

What this does:
  - Valid token with margin        -> do nothing.
  - Expired / expiring soon         -> SILENT refresh via a one-shot
                                       `kiro-cli chat --no-interactive`.
  - Silent refresh fails (RT dead)  -> print the logout+login the user must run
                                       (the only case needing a browser).

Usage:
  python3 kiro-auth.py          # check + silent refresh if needed
  python3 kiro-auth.py -q       # quiet unless action/error
  python3 kiro-auth.py -h       # help

Share with colleagues: same file works on any OS. If it can't find the DB
on Windows, it prints the paths it tried — send that back so we can pin it.

Configuration:
  Your IdP / region / license are NOT hardcoded here. They are read, in order,
  from environment variables, then a local `kiro-auth.config` file next to this
  script (git-ignored), then left blank. They are only used in the rare
  browser-login fallback message. See README.md "First-time setup" and copy
  `kiro-auth.config.example` to `kiro-auth.config` to fill in your own values.
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys

MARGIN_SECONDS = 300  # refresh if the token dies within 5 minutes


def load_config():
    """IdP settings for the fallback message. Env vars win, then a local
    git-ignored config file, then blank placeholders. Never committed."""
    cfg = {"IDP_URL": "", "REGION": "", "LICENSE": "pro"}
    # 1) local config file next to this script (KEY=VALUE lines, # comments)
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "kiro-auth.config")
    if os.path.isfile(path):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip().strip('"').strip("'")
                    if k in cfg:
                        cfg[k] = v
        except Exception:
            pass
    # 2) environment variables override the file
    for k in cfg:
        env = os.environ.get("KIRO_AUTH_" + k)
        if env:
            cfg[k] = env
    return cfg


def candidate_db_paths():
    """Likely locations of kiro-cli's data.sqlite3, most-specific first."""
    home = os.path.expanduser("~")
    paths = []
    if sys.platform == "darwin":
        paths.append(os.path.join(home, "Library", "Application Support",
                                  "kiro-cli", "data.sqlite3"))
    elif os.name == "nt":  # Windows
        for env in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env)
            if base:
                paths.append(os.path.join(base, "kiro-cli", "data.sqlite3"))
        paths.append(os.path.join(home, "AppData", "Local", "kiro-cli",
                                  "data.sqlite3"))
    else:  # Linux / other
        xdg = os.environ.get("XDG_DATA_HOME",
                             os.path.join(home, ".local", "share"))
        paths.append(os.path.join(xdg, "kiro-cli", "data.sqlite3"))
    # Cross-platform fallbacks, just in case.
    paths.append(os.path.join(home, ".local", "share", "kiro-cli",
                              "data.sqlite3"))
    # De-dupe, preserve order.
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def find_db():
    for p in candidate_db_paths():
        if os.path.isfile(p):
            return p
    return None


def remaining_seconds(db_path):
    """Seconds until the live token expires, or None on any problem."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "select value from auth_kv where key='kirocli:odic:token'"
        ).fetchone()
        con.close()
        if not row:
            return None
        d = json.loads(row[0])
        exp = d.get("expires_at") or d.get("expiresAt")
        e = datetime.datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return int((e - now).total_seconds())
    except Exception:
        return None


def kiro_bin():
    return shutil.which("kiro-cli")


def silent_refresh(say):
    """Force a refresh-token renewal via a trivial one-shot authed op."""
    say("-> Nudging a silent refresh (no browser)...")
    try:
        r = subprocess.run(
            ["kiro-cli", "chat", "--no-interactive", "--trust-tools=", "ok"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=90,
        )
        if r.returncode == 0:
            say("OK: token refreshed silently.")
            return True
    except Exception:
        pass
    return False


def main():
    ap = argparse.ArgumentParser(add_help=True, description="Keep kiro-cli auth fresh.")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only print when action is taken or on error")
    args = ap.parse_args()

    def say(*a):
        if not args.quiet:
            print(*a)

    if not kiro_bin():
        print("ERROR: 'kiro-cli' not found on PATH.", file=sys.stderr)
        return 1

    db = find_db()
    if not db:
        print("ERROR: could not locate kiro-cli's data.sqlite3. Tried:",
              file=sys.stderr)
        for p in candidate_db_paths():
            print("  " + p, file=sys.stderr)
        print("Send this list back so the Windows/Linux path can be pinned.",
              file=sys.stderr)
        return 1

    rem = remaining_seconds(db)
    if rem is not None and rem > MARGIN_SECONDS:
        say("OK: token valid for ~%d min. No action needed." % (rem // 60))
        return 0

    say("Token expired or expiring soon.")
    if silent_refresh(say):
        return 0

    cfg = load_config()
    idp = cfg["IDP_URL"] or "<your-sso-start-url>"
    region = cfg["REGION"] or "<your-region>"
    lic = cfg["LICENSE"] or "pro"
    hint = ""
    if not cfg["IDP_URL"] or not cfg["REGION"]:
        hint = ("\n(Set your IdP/region in kiro-auth.config or KIRO_AUTH_* env "
                "vars so this message shows your real values -- see README.)")
    sys.stderr.write(
        "FAILED: silent refresh did not work -- your SSO refresh token has "
        "expired.\n"
        "This is the one case that needs a browser. Run:\n\n"
        "    kiro-cli logout\n"
        "    kiro-cli login --license %s \\\n"
        "      --identity-provider %s \\\n"
        "      --region %s%s\n" % (lic, idp, region, hint)
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
