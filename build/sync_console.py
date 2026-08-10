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

# This script CLONES the repo named in console.lock and runs its build. The lock
# is PR-reviewed rather than untrusted input, so the risk is lower than a pin
# record — but it is the same shape (data naming the code that runs), and an
# allowlist costs nothing. Kept here, in the tool, not in the file it reads.
ALLOWED_CONSOLE_REPOS = {
    "https://github.com/trustless-ai/cross-reference-console",
}


def sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def build(lock: dict) -> bytes:
    """Clone the pinned commit into a temp dir and run its own build."""
    repo = lock["repo"].rstrip("/").removesuffix(".git")
    if repo not in ALLOWED_CONSOLE_REPOS:
        raise SystemExit(
            f"console.lock names {lock['repo']!r}, which is not in this tool's\n"
            "allowlist. Building it would execute code from a repository chosen\n"
            "by a data file. Refusing.")
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
        # Stamp the source commit into the page it was built from. Damon's point,
        # after the code/data split failed both ways in a week: the page must be
        # able to say what it is, because both diagnoses required someone grepping
        # the live HTML by hand.
        #
        # Stamped HERE rather than in the console repo because only the PUBLISHED
        # page has a commit to name — ui/index.html in its own repo cannot know
        # the hash of the commit that will contain it. Inside build() so --check
        # and the write path stamp identically by construction; the substitution
        # is deterministic, so two builds of one commit still compare equal.
        stamped = first.replace(b"__CONSOLE_SOURCE_COMMIT__",
                                lock["commit"].encode())
        if stamped == first:
            raise SystemExit(
                f"the build of {lock['commit'][:12]} contains no "
                "__CONSOLE_SOURCE_COMMIT__ placeholder, so the published page "
                "could not say which commit it came from.\n"
                "Refusing: a page that cannot state its own provenance is exactly "
                "what cost us two hand-diagnoses this week.")
        return stamped


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
