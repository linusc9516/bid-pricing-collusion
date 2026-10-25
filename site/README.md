# Example viewer

A static page for stepping through auction sessions round by round: a winner strip, a bids chart, a per-round
table, each firm's reasoning and hidden thinking, and the exact prompt it was shown, with the matched one-shot
control beside each session. No server, no build step: open `index.html` in a browser.

## After cloning: open `index.html`

Nothing to install and no server. The page opens on **Findings**: the text of `site/FINDINGS.md` (the paper's
results), with the paper's figures as PNG copies in `site/figures/`. **All runs** lists the 11 runs behind the paper
(540 sessions), and every session can be opened round by round, with its messages or notes.

This works on a fresh clone because one bundle is committed:

- `data/published.js`: the run index, the findings page as HTML, and small per-run tables.
- `data/published/<run_id>/<session_id>.js`: one file per session, without hidden thinking, per-call prompts or the
  tool results a notes step was shown (the notes themselves are in the session's notes panel). The 2 to 3 sentence
  reasoning of each bid and every message are kept. About 65 MB for the 11 runs.

Rebuild it after the findings file or a run changes, from a machine that has the logs:

```sh
uv run python scripts/export_site.py --publish baseline_no_channel channel_c1 notes_deepseek notes_luna \
  channel_extensions luna_long luna_replication channel_ablations notice_checks placebo_replay narrow_costs
```

`--findings FILE` uses another Markdown file (default `site/FINDINGS.md`). The figures are converted from
`paper/figures/*.pdf` with `pdftocairo -png -r 220 -singlefile`; `fig_overview.png` is cropped from page 2 of the
built paper, since Figure 1 is TikZ inside the paper. Each rebuild adds its size to the repository's history, so
publish at milestones. A finding heading `### F5. ... (exploratory)` becomes a card with a badge. Live charts under a
finding (`FINDING_CHARTS` in `src/bidrig/viewer.py`) are drawn from the first bundled run and are used only with
`docs/history/BASELINE_FINDINGS.md`, the earlier findings page about the baseline.

## GitHub Pages

`.github/workflows/pages.yml` deploys `site/` on every push to `main` that touches it. Turn it on once under the
repository's Settings, Pages, Source: GitHub Actions. Only committed files are served, so the page shows the
published bundle; a local export (`data/runs.js`, `data/sessions/`) is gitignored and never deployed.

## Build the run pages from your own logs

A fresh clone shows the findings, the examples and the one bundled run. Every other run is built from raw logs, and
neither `logs/` nor the exported `data/runs.js` and `data/sessions/` is in git. A local export of a run takes
precedence over its bundled copy. Build them from the runs on your machine:

```sh
uv run python scripts/export_site.py --no-thinking --no-prompts   # every run under logs/
uv run python scripts/export_site.py <run_id>                     # one run, with prompts and thinking text
uv run python scripts/export_site.py --logs-root <path>           # logs kept somewhere else
```

Then open `index.html` and choose "All runs". The export reads `logs/<run_id>/<condition_id>/<session_id>/`, each
holding `session.json`, `bids.jsonl` and `calls.jsonl` as the runner writes them. It skips sessions that are not
`complete`, and pairs a session with its control by the id `oneshot__<session_id>`. Logs written by a changed
harness need the same layout and fields. To see the runs made here (pilot, rotation screen, follow-up runs), ask
for a copy of that `logs/` directory.

**For a coding agent (Claude Code or similar) working in a fork.** If the export fails or skips sessions because
the logs do not match, fix the mismatch as follows:

- The expected fields are the dataclasses in `src/bidrig/schema.py` (`SessionMeta`, `BidRow`, `CallRow`), described
  in `docs/history/PLANNING.md` section 3. Compare the logs against those first and report every difference before changing anything.
- Never edit the raw logs in place. Write a small converter script that reads them and writes a converted copy to a
  new directory, then export with `--logs-root <that directory>`.
- Keep data the schema has no field for, such as workspace or message entries, in its own file per session (for
  example `messages.jsonl`). Do not drop it and do not force it into `bids.jsonl` or `calls.jsonl`.
- Do not fill a missing field with a guess. If a value such as the seed, the cost or the benchmark bid cannot be
  recovered from the logs, stop and ask.
- Do not loosen `schema.py`, `viewer.py` or the tests to make the export pass. If the schema itself has to grow,
  propose the change and wait for a decision.

## What it shows now

Seven hand-picked sessions from the pilot and the rotation screen, listed in `examples.yaml` (run, session id,
matched control, blurb). They were chosen to illustrate a behaviour, not to be typical.

```sh
uv run python scripts/export_examples.py      # logs/ + site/examples.yaml -> site/data/examples.js
```

`data/examples.js` is committed (about 2.5 MB, hidden thinking cut to 2,500 characters per call) because `logs/`
is not. Direct links: `index.html#/<example id>/<0 = repeated, 1 = control>/<round>`.

## All runs

```sh
uv run python scripts/export_site.py                   # every run in logs/ with a complete session
uv run python scripts/export_site.py pilot costrange   # chosen runs
uv run python scripts/export_site.py --no-thinking --no-prompts   # much smaller
```

It writes `data/runs.js` (the run index: one entry per session with settings, headline metrics and a compact
winner string) and `data/sessions/<run_id>/<session_id>.js` (one file per session, loaded on demand when its page
opens). Both are gitignored; only `examples.js` is committed. Pages, linked by URL fragment:

- `#/runs`: one row per run.
- `#/run/<run_id>`: four charts over the run's bids, then its conditions. "Where bids sit, by cost role" classifies
  each valid bid as below own cost, below, at (within 1 bid unit, or one increment on a coarser grid) or above the
  equilibrium bid, one bar per model, cost role (the round's lowest-cost firm or not) and arm, with the share of
  those bids that won. "Bid against own cost" plots every valid bid against the firm's cost, one panel per model and
  arm, with the equilibrium bid, bid = cost and a fitted line; panels over 3,000 bids draw an even sample. "Each
  session against its one-shot control" has one dot per session, each repeated session joined to its control, for a
  chosen measure (index, markup ratio overall or by cost role, slope, intercept): the comparison the session-level
  tests make. "Bid minus equilibrium bid" is the histogram of distances.
  Each condition has mean index, range, mean delta, tie rate and lowest-cost win share
  (n/a under `least_wins`), then every session's winner strip above its matched control's. Filters by model,
  bidder count and tie rule appear when the run has more than one.
- `#/s/<run_id>/<session_id>/<0 = repeated, 1 = control>/<round>`: the full session view used by the examples.

A session with a shared notes workspace or an open message channel (`workspace.jsonl` or `messages.jsonl` in its
directory) gets one more panel above the round view: every note or message, oldest first, grouped by the round
after which it was written, with the writer, a mark on a note cut at the length limit, and a count of reads that
showed a firm another firm's notes ("Show reads" lists each read). The group of the selected round is outlined;
selecting a group opens its round. In the round view, each firm's card then lists its reflection or communication
step after the bid: one entry per request, with the tools it called, the note or message as written, the hidden
thinking, and what the firm was shown, including the tool results returned earlier in the step. The export reads
the two files by name and needs no schema field for them; reading the `session.json` of such a session needs the
`workspace` and `channel` fields of the branch that adds those arms.

A control is found by the id `oneshot__<session_id>`. Sessions that are not `complete` are skipped. Means are
descriptive; the viewer computes no tests or intervals. Not yet built: cross-run comparison, and a CSV download.

## Note: what is left

- **Compare across runs.** Key cells on model, N, tie rule, bid increment, rounds, thinking mode, cost spread and
  prompt version, read from `session.json`, not from `condition_id`, which omits some of them.
- **Curated examples as links** into the run pages instead of their own bundle (`examples.js` is still separate).
- **Size.** With prompts and thinking text a pilot-sized run is about 65 MB (about 25 MB without thinking text);
  use the export flags above and keep `data/sessions/` out of git except for runs chosen for sharing. GitHub Pages
  caps a site at 1 GB.

Constraints to keep:

- **Size.** With prompts and thinking text a pilot-sized run is about 65 MB (about 25 MB without thinking text);
  the planned main experiment would be 150 to 250 MB. Options: `--no-thinking` and `--no-prompts` export flags, and
  keeping `data/<run_id>/` out of git except for runs chosen for sharing. GitHub Pages caps a site at 1 GB.
- **Private costs.** The page shows every firm's cost and BNE bid. It is a researcher view and is never shown to
  an agent, so the rule that agents never see other agents' costs is untouched. An "agent's view" toggle would
  have to mirror `prompts.visible_rows` and be tested against it.
- **No inference in the viewer.** It shows metrics already computed by `analysis/metrics.py`.
- **No framework, no external JavaScript**, so any static host can serve it.

Reference for the layout: the [Agent Collusion Explorer](https://salt-nlp.github.io/agent-collusion-website/)
(SALT-NLP), adapted from chat episodes to sealed-bid rounds. The longer original plan was `VISUALISER_PLAN.md`,
removed on 6 October 2026 (last present at commit `a413d25`).
