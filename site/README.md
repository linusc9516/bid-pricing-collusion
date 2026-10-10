# Example viewer

A static page for stepping through auction sessions round by round: a winner strip, a bids chart, a per-round
table, each firm's reasoning and hidden thinking, and the exact prompt it was shown, with the matched one-shot
control beside each session. No server, no build step: open `index.html` in a browser.

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
- `#/run/<run_id>`: two charts over the run's bids, then its conditions. "Where bids sit, by cost role" classifies
  each valid bid as below own cost, below, at (within 1 bid unit, or one increment on a coarser grid) or above the
  equilibrium bid, one bar per model, cost role (the round's lowest-cost firm or not) and arm, with the share of
  those bids that won. "Bid minus equilibrium bid" is the histogram of distances, which the classes do not show.
  Each condition has mean index, range, mean delta, tie rate and lowest-cost win share
  (n/a under `least_wins`), then every session's winner strip above its matched control's. Filters by model,
  bidder count and tie rule appear when the run has more than one.
- `#/s/<run_id>/<session_id>/<0 = repeated, 1 = control>/<round>`: the full session view used by the examples.

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
