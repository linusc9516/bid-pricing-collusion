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

## Limit: it does not track runs

Adding a session means editing `examples.yaml` by hand and re-exporting. There is no list of runs, no table of
conditions, and no way to see every session of a cell. With more models and runs coming, a curated list will not
scale, and a picked example can be mistaken for a typical one.

## Note: making it general

The aim is one place to browse every run, with curated examples as bookmarks into it. Not built. Outline:

1. **Export per run, not per example.** `export_site.py logs/<run_id>` writes `data/<run_id>/index.json` (run
   metadata, conditions, one entry per session with its `session_metrics.csv` row and a compact winner string)
   and `data/<run_id>/sessions/<session_id>.json` (what the page shows for one session today). `data/runs.json`
   lists the exported runs. Session files load on demand, so the page stays fast as runs are added.
2. **Three levels, linked by URL fragment.**
   - Overview `#/`: run picker, then a model x condition table (index, control index, delta, lowest-cost-wins
     share, tie rate, reserve-bid rate) with a sample-size caption.
   - Condition `#/c/<condition_id>`: one row per session, its winner strip directly above its control's.
   - Session `#/s/<session_id>/r/<round>`: the current example view.
3. **Curated examples become links.** `examples.yaml` keeps the titles and blurbs and points at session routes.
4. **Compare across runs.** Key cells on model, N, tie rule, bid increment, rounds, thinking mode and prompt
   version, read from `session.json`, not from `condition_id`, which omits the last four.
5. **Keep metric validity visible.** Grey the win-pattern columns under `least_wins` (`PLANNING.md` 6.4).

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
