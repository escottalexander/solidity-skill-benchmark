# Fresh (post-cutoff) Solidity audit candidates for benchmark evals

Researched 2026-07-04/05. All repos + exact commits verified live via GitHub
API. These audits were published after 2026-03-01, so their findings cannot be
in the benchmarked models' training data — they fix the contamination gap
(FINDINGS.md §12) and, being full pinned repos, they compile (tooling arm).

Report PDFs/text for extraction are cached in `.cache/reports/`. The
machine-readable candidate list is `docs/fresh_audit_candidates.json` (kept
OUT of `evals/import_specs/` so the importer's `*.json` glob doesn't treat it
as a spec).
Import via `evals/import_specs/TEMPLATE.json.example` + `scripts/import_recent_audit.py`.

## Top picks (Foundry, verified pre-fix commits, rich C/H/M findings)

| Project | Firm | Published | C/H/M | Scope | Repo @ commit |
|---|---|---|---|---|---|
| Tenbin Core Contracts | Zellic | 2026-05-13 | 1/3/3 | ~9 contracts | tenbinlabs/tenbin-contracts @ 820e7009 |
| Alt Fun | Guardian | 2026-07-01 | 1/1/3 | 8 contracts | alt-fun/contracts @ 625fd214 |
| Armada Crowdfund & Governance | Cyfrin | 2026-05-20 | 0/3/10 | ~11 contracts | ship-armada/armada-poc @ a009580c (confirm vs PDF; 5b525ef8 = fixes) |
| Compound Bytecode Repository | Certora | 2026-05-31 | 1/1/4 | 8 files | woof-software/bytecode-repository @ 93219299 (code Sep 2025) |
| Shift DeFi Platform | MixBytes | 2026-05-13 | 1/11/6 | ~15 contracts | ShiftDeFi/shift-defi-platform @ 97902065 (+4 adapter repos; code Dec 2025) |
| Spiral Stake V2 | Cyfrin | 2026-05-21 | 1/2/9 | 7 files | spiral-stake/v2-core @ ead97aa2 (code Feb 2026) |

## Second tier

- **GroveLabs Basin** (ChainSecurity, 2026-06-18, 0/0/3, Foundry) — grove-labs/grove-basin @ 24da7756
- **Bebop Router** (Cyfrin, 2026-06-17, 0/1/2, Hardhat) — bebop-dex/bebop-rfqa @ 528826ac
- **Relay Settlement** (Zellic, 2026-06-29, 1/1/3, Foundry+Hardhat) — relayprotocol/relay-settlement @ 376652bc (contracts under smart-contracts/)
- **3F Grunt Funds** (ChainSecurity, 2026-04-08, 0/0/4, Foundry) — 3FLabs/grunt @ 6e391591 (main-protocol report 1H/16M @ fb03efa5 spans 58 files)
- **MEV-X Homelander** (MixBytes, 2026-05-12, 0/0/3, Hardhat, 2 contracts)
- **Sablier Bob/Escrow** (Cyfrin, 2026-03-25, 1/1/4) — borderline freshness (code Feb 2026)
- **Apyx Stablecoin** (Zellic, 2026-03-20, 1/0/2) — borderline freshness (audit Jan 2026)

## Use with caution

- **Myriad CLOB** (Cyfrin, 0/2/1) — FORK FLAG: mirrors Polymarket CTF Exchange architecture (pre-2026)
- **Term Finance v2** (Sigma Prime, 9/6/24!) — public commit is POST-FIX; pre-fix repo private; ~40 files
- **Aragon Generic Money** (Spearbit, 0/2/2) — review Nov 2025, weakest freshness

## Negative results (so nobody re-searches these)

- **Pashov**: zero qualifying — every ≥3 H/M report targets a private repo.
- **Trail of Bits**: zero — all small diff reviews, best 2 H/M.
- **OpenZeppelin / Consensys**: nothing qualifying after 2026-03-01.
- **Contest platforms (C4/Sherlock/Cantina/CodeHawks)**: research crippled by fetch failures; only 2 unverified CodeHawks leads (2026-04-snarkeling, 2026-07-battlechain-confidence-pools) — worth a retry later since contest repos are ideal (frozen + structured findings).
- **Private-repo near-misses to recheck if they open-source**: Trueo (4H/22M), Catalysis (5C/5H/5M), AFX Bridge, STBL (2C/8H/8M), CrossCurve CDP, Megapot v2, Umia, Molecule OnChainLab.
