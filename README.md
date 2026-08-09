# trustless-ai-landing

The site published at **[trustless-ai.eth](https://trustless-ai.eth.limo)** — the
org's front page, the press page, the game, and the
[cross-reference console](https://trustless-ai.eth.limo/console/index.html).

This repo exists because the site was not in version control at all, and that one
fact broke the publishing story end to end.

## Why it had to be a repo

The ENS contenthash is **the only pointer in this stack that is not
recomputable.** Every other value — `claim_id`, `evidence_hash`, the signer, an
edge — a stranger can re-derive from primary sources. The pin is a transaction we
send, pointing at bytes we chose.

The group agreed a rule for it ([PIN-RECORD.md][pin] in the console repo):

> **No unilateral pin.** A CID is pinned only once two independent parties have
> each rebuilt the stated commit and got the same bytes and the same CID.

That rule could not actually be run. Three reasons, all found by trying:

1. **The contenthash covers a directory**, `bafybei…`, all 29 files here — not
   just the console page. A pin record covering one file says nothing about the
   other twenty-eight.
2. **Twenty-eight of those files were in nobody's repo.** There was no commit for
   a second party to rebuild from, so the second party could not exist.
3. **We could not reproduce the CID that was already live.** The local folder
   hashed to something else, and the `ipfs add` flags used originally were not
   recorded anywhere.

And the console page that *was* published matched no commit in the console repo —
it had been hand-copied from someone's working directory.

## How the site is built

Everything here is a source file except one, which is **derived**:

```bash
python3 build/sync_console.py        # console/index.html ← the commit in console.lock
python3 build/sync_console.py --check   # verify it, change nothing (this is what CI runs)
```

`console/index.html` is built from `cross-reference-console` at the exact commit
pinned in [`console.lock`](console.lock) — never copied by hand. To publish a
newer console, bump the commit in that file and re-run the sync.

The sync **builds the locked commit twice and fails if the two differ**. A console
commit that does not build deterministically cannot be published under the pin
rule at all, since no second party could ever reproduce its CID.

## Getting the CID

```bash
python3 build/site_cid.py
```

```
files published : 29
tree hash       : sha256:604fa5d8…
cid_params      : {"chunker":"size-262144","cid_version":1,…}
directory CID   : bafybei…
```

Two values, deliberately:

- **tree hash** — depends on the bytes alone. This is what proves two independent
  rebuilds agree.
- **directory CID** — depends on the bytes *and* the `ipfs add` parameters in
  [`site.pin.json`](site.pin.json). This is what gets pinned.

They are separate because they fail differently. Two people can build this site
faithfully, produce byte-identical trees, and still report different CIDs if their
flags differ — a **parameter disagreement**, not a tampered page. Conflating those
two findings is how a mechanism like this loses its credibility on first use.

## Publishing

```bash
# 1 · pull in the console page from its locked commit, and commit the result
python3 build/sync_console.py
git commit -am "console: <what changed>"

# 2 · derive the values that go in the pin record
python3 build/site_cid.py --json
```

3 · Write `pins/<cid>.json` in the console repo with `artifact_kind: "site-tree"`,
this repo's commit, the tree hash, the CID and `cid_params`.

4 · **Two** registered nodes each rebuild and sign:

```bash
export CRC_KEY=0x…
python3 reference/sign_confirmation.py --record pins/<cid>.json --node <yournode>
```

5 · The gate:

```bash
python3 reference/verify_pin.py pins/<cid>.json     # must print GREEN
```

**AMBER is not permission to proceed.** It means something could not be
established, and could-not-check is never a pass.

6 · Add the bytes **on a node you control**, with the recorded parameters — the
same ones `site.pin.json` names, so the CID is the one that was confirmed:

```bash
ipfs add -Q -r --cid-version=1 --chunker=size-262144 --hash=sha2-256 \
  --ignore .git --ignore .github --ignore build --ignore __pycache__ \
  --ignore console.lock --ignore site.pin.json --ignore README.md --ignore .gitignore .
```

That must print **exactly** the CID in the pin record. If it does not, stop: you
are about to pin something nobody confirmed.

7 · For durability, ask a pinning service to **pin that CID** (Pinata's
"pin by CID" / `pinByHash`). Do **not** re-upload the folder to the service.
A service that re-adds the files applies *its own* chunker, cid-version and
wrapping, and hands back a **different CID** — which is the parameter trap
arriving at the last possible moment, after every confirmation has been signed
against the other value. Replicating a CID cannot change it; re-uploading can.

8 · Set the contenthash to that CID.

Steps 6–8 are the only ones that are not reproducible by a third party, which is
exactly why 3–5 exist.

[pin]: https://github.com/trustless-ai/cross-reference-console/blob/main/PIN-RECORD.md
