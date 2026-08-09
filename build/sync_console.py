#!/usr/bin/env python3
"""Build console/index.html from the console repo at the commit in console.lock.

Why this exists: `console/index.html` used to be hand-copied here from someone's
working directory. That single fact broke the whole publishing story —

  * the published page corresponded to no commit anyone could name (the live one
    matched neither `main` nor any branch when we checked),
  * so nobody could rebuild it, so nobody could verify the CID,
  * so the pin was an act of trust in whoever ran `cp`.

That is the one thing the ENS contenthash cannot afford, because it is the only
pointer in this stack that is not recomputable, and the console's embedded
snapshot is the matrix's primary data source. A tampered page shows fabricated
nodes and fabricated GREEN cells on the org's own domain.

So the page is *derived* here, from a pinned commit, by anyone, at any time.

    python3 build/sync_console.py            # write console/index.html
    python3 build/sync_console.py --check    # verify it matches, change nothing

`--check` is what CI runs: if the committed page is not what the locked commit
builds, the site has drifted from its sources and must not be pinned.
"""

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "console.lock"


def sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def build(lock: dict) -> bytes:
    """Clone the pinned commit into a temp dir and run its own build."""
    with tempfile.TemporaryDirectory() as td:
        wt = pathlib.Path(td) / "console"
        r = subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                            lock["repo"] + ".git", str(wt)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"clone failed: {r.stderr.strip()[:200]}")
        r = subprocess.run(["git", "checkout", "--quiet", lock["commit"]],
                           capture_output=True, text=True, cwd=wt)
        if r.returncode != 0:
            raise SystemExit(
                f"commit {lock['commit'][:12]} not found in {lock['repo']}.\n"
                "If it is on an unmerged branch, it must be pushed and reachable.")
        r = subprocess.run([sys.executable, "ui/embed_snapshot.py"],
                           capture_output=True, text=True, cwd=wt)
        if r.returncode != 0:
            raise SystemExit(f"console build failed:\n{r.stderr.strip()[:400]}")
        art = wt / lock["artifact"]
        if not art.exists():
            raise SystemExit(f"build produced no {lock['artifact']}")
        first = art.read_bytes()

        # Build twice. A console commit whose build is not deterministic cannot
        # be published under the two-party pin rule at all — better to fail here,
        # loudly, than to pin something no second party can reproduce.
        b2 = subprocess.run([sys.executable, "ui/embed_snapshot.py"],
                            capture_output=True, text=True, cwd=wt)
        # Check the SECOND build too. If it fails, the first build's artifact is
        # still sitting there, so reading it back would compare a file to itself
        # and report determinism that was never demonstrated.
        if b2.returncode != 0:
            raise SystemExit(
                f"second build of {lock['commit'][:12]} failed, so determinism was\n"
                "never demonstrated — the first build's artifact is still in place\n"
                "and comparing it to itself would prove nothing.\n"
                + (b2.stderr.strip().splitlines() or ["(no stderr)"])[-1][:200])
        second = art.read_bytes()
        if first != second:
            raise SystemExit(
                f"console commit {lock['commit'][:12]} does NOT build deterministically —\n"
                "two builds of one commit differ, so no second party could ever confirm\n"
                "the CID. Lock a commit that includes the reproducible-build fix.")
        return first


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed page matches; write nothing")
    args = ap.parse_args()

    lock = json.loads(LOCK.read_text())
    dest = ROOT / lock["installs_to"]
    built = build(lock)

    if args.check:
        if not dest.exists():
            print(f"FAIL  {lock['installs_to']} does not exist")
            return 1
        have = dest.read_bytes()
        if have != built:
            print(f"FAIL  {lock['installs_to']} is not the build of "
                  f"{lock['commit'][:12]}\n"
                  f"        committed: {sha(have)}\n"
                  f"        rebuilt:   {sha(built)}\n"
                  f"      The site has drifted from its sources — do NOT pin.\n"
                  f"      Fix: python3 build/sync_console.py")
            return 1
        print(f"ok    console/index.html is the build of {lock['commit'][:12]} "
              f"({sha(built)[:22]}…)")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    changed = (not dest.exists()) or dest.read_bytes() != built
    dest.write_bytes(built)
    print(f"{'updated' if changed else 'unchanged'}  {lock['installs_to']} "
          f"← {lock['commit'][:12]}  {sha(built)[:22]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
