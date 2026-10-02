# Prep Log

Dated record of work done before the official sprint weekend (Oct 23-25, 2026),
kept for the sprint's disclosure requirement ("must clearly identify what is
new work done during the sprint").

## Format
- YYYY-MM-DD: brief description of what was designed/built/decided

## Entries
(add entries here as prep work happens)

- 2026-10-02: Repo scaffolded: directory layout, configs, dependency setup, docstring-only module stubs. No experiment, auctioneer or analysis logic implemented.
- 2026-10-02: Implementation plan written (PLANNING.md): components, data schema, build order, open questions.
- 2026-10-02: Analysis design decided: required one-shot control, collusion index reported unclipped, session as the unit of analysis, pre-declared comparisons with Holm correction.
- 2026-10-02: Tie-break rule experiment designed (random / least-wins-first / BAFO rebid) and made the main claim, with the three original ablations as reduced-scale supporting context.
- 2026-10-02: Pooled and per-model test variants set up on separate branches (`scaffold-and-analysis-plan`, `per-model-tests`).
- 2026-10-02: $10 budget plan, two-phase execution plan (Phase A pre-team pilot, Phase B full run), and known risks and contingencies documented. CLAUDE.md added.
- 2026-10-02: Phase A pilot config written (three models, three tie-break rules, 5 sessions of 25 rounds, with one-shot controls). Not yet run.
- 2026-10-02: Literature review of prior work on LLM and algorithmic collusion in auctions, tie-break rules, bid rotation, rebids and bid-rigging screens (`reports/LLM bidder collusion prior work.md`, source notes in `research_notes/`). Produced with AI research assistance; several sources read as abstracts only, as marked in the report.
- 2026-10-02: Least-wins-first reframed as a design choice, not a claim about existing procurement rules, after the review found no regulation that breaks tied bids that way.
- 2026-10-02: Heo, Ahn & Park (2026) read in full; comparison with this design recorded in PLANNING.md section 8 and the literature report. Its tie rule is fixed at random and never varied.
- 2026-10-03: Six more papers read in full (Puzzello 2008, Davis & Wilson 2002, Sherstyuk 1999, Comanor & Schankerman 1976, Athey, Bagwell & Sanchirico 2004, Heo, Park & Ahn 2024); three were scanned images read by machine OCR. Literature report and source notes updated. One correction: human-subject experiments have varied a tie rule, so the novelty claim is narrowed to LLM bidders, learning algorithms, win-history-conditioned rules and rebids.
- 2026-10-03: Heo, Ahn, Oh & Park (2025, reinforcement-learning bidders) read in full; report and notes updated. Its collusive end state is a tie at the bid cap, and it does not state a tie rule.
- 2026-10-03: Decided Phase A bid calls include short reasoning (two or three sentences); Phase B reasoning length left open with a reminder in PLANNING.md, configs and CLAUDE.md. Reserve price (100) and bid increment (0.01) marked resolved.
- 2026-10-03: Fourth model set to Qwen3.7 Flash (qwen/qwen3.7-flash, $0.03/$0.13 per million), checked against the live OpenRouter list. Qwen3.8 Flash was considered and rejected on cost: its listed price is $0.15/$0.47. Budget estimate revised to $5.92.
- 2026-10-03: All four OpenRouter slugs verified against the live list; listed prices differ from the design document (DeepSeek output $0.60, GLM $0.90). Phase A narrowed to DeepSeek V4.1 Flash and GPT-oss-120b with a $10 budget (estimate about $0.50); Phase B budget left TBD, expected to be higher.
