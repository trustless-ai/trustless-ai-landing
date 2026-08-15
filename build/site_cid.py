#!/usr/bin/env python3
"""Compute the CID of the whole site — the value the ENS contenthash points at.

The contenthash is a **directory** CID (`bafybei…`, dag-pb), covering every file
here, not just the console page. That distinction cost us a real gap: the pin
record originally covered one file out of twenty-nine, so a second party could
have confirmed `console/index.html` and said nothing about the other twenty-eight.

The `ipfs add` parameters live in `site.pin.json` and are not decoration. The same
bytes give a different CID under `--cid-version=0` vs `1`, and different again
wrapped with `-w`. Two people can each build this site faithfully, produce
byte-identical trees, report different CIDs, and both conclude the other is wrong.
Fixing the parameters is what makes "we both got the same CID" a meaningful claim.

    python3 build/site_cid.py            # print the directory CID + tree hash
    python3 build/site_cid.py --json     # machine-readable, for a pin record
    python3 build/site_cid.py --store    # ALSO store the bytes, and pin them

Requires an `ipfs` binary for the CID. Without one it still prints the tree hash
— which is the byte-agreement authority — and says plainly that the CID was not
computed. Could-not-check is never a pass.

WHY `--store` EXISTS. The derivation runs `ipfs add -n`, which is hash-only: it
stores NOTHING. That is correct for asking "what would the CID be", and it is a
trap at the one moment that matters. On the 15 August repin it printed a CID for
bytes that existed in no repository anywhere, the contenthash was set to it, and
the site was unreachable until the bytes were added separately by hand — a
published pointer to nothing, which is worse than a stale pointer because it looks
deliberate.

So storing is now part of the tool rather than a step someone has to remember, and
the equality is the check: `--store` re-runs the SAME command without `-n` and
refuses to report success unless the stored CID equals the derived one. Different
CIDs mean the parameters drifted between the two runs, and the honest outcome then
is exit 2 — not a pin.
"""

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PARAMS = ROOT / "site.pin.json"

# Never published, so never part of what is pinned.
EXCLUDE_DIRS = {".git", ".github", "build", "__pycache__"}
EXCLUDE_FILES = {"console.lock", "site.pin.json", "README.md", ".gitignore"}


def published_files():
    """Every file that is actually part of the site, in stable order."""
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if set(rel.parts) & EXCLUDE_DIRS:
            continue
        if rel.as_posix() in EXCLUDE_FILES or rel.parts[0].startswith("."):
            continue
        out.append(rel)
    return out


def tree_hash(files) -> str:
    """A single hash over the published tree: path + content, in sorted order.

    Independent of any IPFS setting, so two parties can agree on the BYTES even
    when their ipfs flags differ — which is precisely the case that should read
    as a parameter disagreement rather than as tampering.
    """
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.as_posix().encode())
        h.update(b"\0")
        h.update(hashlib.sha256((ROOT / rel).read_bytes()).digest())
    return "sha256:" + h.hexdigest()


def site_cid(params: dict, store: bool = False):
    """Derive the directory CID. With store=True the bytes are actually written.

    `-n` is the ONLY difference between the two calls. Keeping them one function
    is deliberate: two functions would let the parameters drift, and a stored CID
    that differs from the derived one is exactly the disagreement this whole file
    exists to make impossible.
    """
    if not shutil.which("ipfs"):
        return None
    args = ["ipfs", "add", "-Q", "-r"] if store else ["ipfs", "add", "-Q", "-n", "-r"]
    args.append(f"--cid-version={params.get('cid_version', 1)}")
    if params.get("wrap_with_directory"):
        args.append("-w")
    if params.get("chunker"):
        args.append(f"--chunker={params['chunker']}")
    if params.get("hash"):
        args.append(f"--hash={params['hash']}")
    # Explicit, never inherited. --cid-version=1 implies raw-leaves=true today,
    # but relying on that means the CID depends on an ipfs default we do not
    # control and did not record.
    if params.get("raw_leaves") is False:
        args.append("--raw-leaves=false")
    elif params.get("raw_leaves") is True:
        args.append("--raw-leaves=true")
    # Exclusions must match `published_files()`, or the CID would cover a
    # different set than the tree hash and the two would silently disagree.
    for d in sorted(EXCLUDE_DIRS | {f for f in EXCLUDE_FILES}):
        args += ["--ignore", d]
    args.append(str(ROOT))
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    return lines[-1].strip() if lines else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--store", action="store_true",
                    help="also STORE the bytes (not just hash them) and pin them locally")
    args = ap.parse_args()

    params = json.loads(PARAMS.read_text())["cid_params"]
    files = published_files()
    th = tree_hash(files)
    cid = site_cid(params)

    if args.store:
        if cid is None:
            print("UNVERIFIABLE — no usable `ipfs` binary, so nothing was stored.", file=sys.stderr)
            return 2
        stored = site_cid(params, store=True)
        if stored is None:
            print("UNVERIFIABLE — the store run failed; the bytes may not be held.", file=sys.stderr)
            return 2
        if stored != cid:
            # Never pin, never report success. The two runs disagreed about what
            # they were describing, and a contenthash set from either would be a
            # pointer whose meaning nobody can reproduce.
            print(f"FAIL  derived {cid}\n      stored  {stored}\n"
                  f"      The two runs disagree — the parameters drifted between them.",
                  file=sys.stderr)
            return 1
        pin = subprocess.run(["ipfs", "pin", "add", "--recursive", stored],
                             capture_output=True, text=True)
        if pin.returncode != 0:
            print(f"UNVERIFIABLE — stored {stored} but could not pin it: "
                  f"{pin.stderr.strip().splitlines()[-1] if pin.stderr.strip() else '(no output)'}",
                  file=sys.stderr)
            return 2
        print(f"  stored and pinned : {stored}")
        print("                      derived and stored CIDs agree — these bytes exist locally")

    if args.json:
        print(json.dumps({"tree_sha256": th, "cid": cid, "cid_params": params,
                          "file_count": len(files)}, indent=2))
        return 0

    print(f"  files published : {len(files)}")
    print(f"  tree hash       : {th}")
    print(f"  cid_params      : {json.dumps(params, sort_keys=True)}")
    if cid:
        print(f"  directory CID   : {cid}")
    else:
        print("  directory CID   : NOT COMPUTED — no usable `ipfs` binary.")
        print("                    The tree hash above still pins the bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
