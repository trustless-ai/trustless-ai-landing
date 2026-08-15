#!/usr/bin/env python3
"""Is console.lock CURRENT with cross-reference-console, or merely internally consistent?

WHY THIS EXISTS. On 2026-08-15 the published console was serving a build from 10 August while
the fix it needed had been on `cross-reference-console` main since the 13th. Every check in the
chain was green, and every one was honest about its own link:

  * `sync_console.py --check` — console/index.html IS the deterministic build of the commit in
    console.lock. True.
  * cross-reference-console's `check_console_reproducible.py` — ui/index.html IS the
    deterministic build of its commit. True.
  * `check_console_currency.py` (in cross-reference-console) — the ENS contenthash IS the
    deterministic site-tree of landing HEAD. True.

Three green checks, and the console a reader loaded was two days and fifteen commits stale. No
check was wrong; the LOCK was, and nothing was looking at the lock. A pin is a claim about
which commit is published, never a claim that it is the one you would want.

VOCABULARY, deliberately the same as cross-reference-console's currency check so the two
compose rather than competing:

  CURRENT       console.lock names the tip of the upstream default branch
  STALE         determinate — names both commits AND the range between them, because the
                difference proves it is behind while the range is what tells a human whether
                that is one merge or a month
  UNDETERMINED  could not be established, with a REQUIRED reason:
                  upstream_unreachable  — the remote could not be queried
                  lock_unreadable       — console.lock missing or malformed
                Never a silent not-current.

EXIT: 0 CURRENT · 1 STALE · 2 UNDETERMINED. Could-not-check is never a pass.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "console.lock"

CURRENT, STALE, UNDETERMINED = "CURRENT", "STALE", "UNDETERMINED"
EXIT = {CURRENT: 0, STALE: 1, UNDETERMINED: 2}


def read_lock() -> tuple[dict | None, str | None]:
    try:
        d = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"lock_unreadable ({e.__class__.__name__})"
    if not isinstance(d, dict) or not d.get("commit") or not d.get("repo"):
        return None, "lock_unreadable (missing commit or repo)"
    return d, None


def upstream_head(repo_url: str, branch: str = "main") -> tuple[str | None, str | None]:
    """The tip of the upstream branch. Tries the API, falls back to git ls-remote."""
    slug = repo_url.rstrip("/").removeprefix("https://github.com/")
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{slug}/commits/{branch}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "console-currency"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)["sha"], None
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        pass
    try:
        out = subprocess.run(["git", "ls-remote", repo_url, f"refs/heads/{branch}"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.split()[0], None
    except (subprocess.SubprocessError, OSError):
        pass
    return None, "upstream_unreachable (API and ls-remote both failed)"


def behind_by(repo_url: str, base: str, head: str) -> tuple[int | None, list[str]]:
    """How far behind, and what is missing. Best-effort: absence of detail never upgrades
    the verdict, it only makes the report thinner."""
    slug = repo_url.rstrip("/").removeprefix("https://github.com/")
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{slug}/compare/{base}...{head}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "console-currency"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
        subjects = [c["commit"]["message"].split("\n")[0] for c in d.get("commits", [])]
        return d.get("ahead_by"), subjects
    except Exception:
        return None, []


def main() -> int:
    print("\ncurrency of console.lock\n")

    lock, err = read_lock()
    if lock is None:
        print(f"  {UNDETERMINED} — reason: {err}", file=sys.stderr)
        print("  the lock could not be read, so nothing is claimed about what is published.", file=sys.stderr)
        return EXIT[UNDETERMINED]

    locked, repo = lock["commit"], lock["repo"]
    head, err = upstream_head(repo)
    if head is None:
        print(f"  {UNDETERMINED} — reason: {err}", file=sys.stderr)
        print(f"  locked at {locked[:12]}; upstream could not be consulted, which is not the same", file=sys.stderr)
        print("  as being current. Re-run when the network allows.", file=sys.stderr)
        return EXIT[UNDETERMINED]

    if locked == head:
        print(f"  ok    · console.lock names {locked[:12]}, the tip of {repo.split('/')[-1]} main")
        print(f"\n{CURRENT} — the published console is built from upstream HEAD")
        return EXIT[CURRENT]

    n, subjects = behind_by(repo, locked, head)
    print(f"  locked   : {locked}")
    print(f"  upstream : {head}")
    print(f"  behind   : {n if n is not None else 'unknown'} commit(s)")
    if subjects:
        print("\n  not published (newest first):")
        for s in subjects[::-1][:10]:
            print(f"      {s[:96]}")
        if len(subjects) > 10:
            print(f"      … and {len(subjects) - 10} more")
    print(f"\n{STALE} — console.lock is behind upstream. Bump it and re-run build/sync_console.py.")
    print("  (This is determinate: both commits are named above, and the range is what says")
    print("   whether that is one merge or a fortnight.)")
    return EXIT[STALE]


if __name__ == "__main__":
    sys.exit(main())
