# Configs

Every config inherits `base.yaml` and overrides what it varies. A run id groups one or more configs; launch them with
`--run-id <run id>` so their sessions land in one `logs/<run id>/`. A `*_tiny.yaml` config is the smoke test of the
config of the same name: one or two sessions of three rounds, run under a `smoke_*` run id before the full launch.

Every test is declared in [`analysis.yaml`](analysis.yaml), in a section named after the run id, committed before
that run's first session. Do not change a setting in a declared config without changing its section there.

## Shared files

| File | What |
|---|---|
| `base.yaml` | Defaults every config inherits |
| `models.yaml` | The only models a config may call, with host tiers and prices |
| `analysis.yaml` | Declared hypotheses, tests, exclusions and readings, one section per run |
| `ext_common.yaml` | Shared settings of the `channel_extensions` configs |
| `abl_common.yaml` | Shared settings of the `channel_ablations` and `notice_checks` configs |
| `replay/` | Recorded bid sequences that the scripted firm replays in `placebo_replay` |

## Runs in the paper

All runs are two firms, private costs drawn U[0, 100] each round, reserve 100, 50 rounds, random tie-break and full
bid history, unless the table says otherwise.

| Run id | Config(s) | Arms | Hypotheses |
|---|---|---|---|
| `baseline_no_channel` | `baseline_no_channel.yaml` | B0 (history) and one-shot control; DeepSeek, Luna | H1, H2 |
| `notes_luna` | `notes_luna_private.yaml`, `notes_luna_shared.yaml` | M1 private notes, M2 shared notes; Luna | H3, H4 |
| `channel_c1` | `channel_c1.yaml` | C1 open message channel; DeepSeek, Luna | H5 |
| `notes_deepseek` | `notes_deepseek_private.yaml`, `notes_deepseek_shared.yaml` | M1, M2; DeepSeek | H9, H10 |
| `placebo_replay` | `placebo_replay.yaml` | One model against a scripted firm replaying high or low recorded bids | H6 |
| `narrow_costs` | `narrow_costs_rescaled.yaml`, `narrow_costs_reserve100.yaml` | Costs U[40, 60]; reserve 60 (rescaled) or 100 | H11, H12 |
| `channel_extensions` | `ext_r1_haiku.yaml` to `ext_r6_n3.yaml` | R1 Haiku; R2 50-character cap; R3 oversight notice; R4 DeepSeek x Luna; R5 DeepSeek x Haiku; R6 three DeepSeek firms | H13-H18 |
| `luna_long` | `luna_long.yaml` | B0, C1; Luna, 100 rounds, new seeds | H19 |
| `luna_replication` | `lunarep.yaml` | B0, C1; Luna, 24 new seeds | H25 |
| `channel_ablations` | `abl_a1_bafo.yaml` to `abl_a5_wording.yaml` | A1 BAFO rebid; A2 winner-only history; A3 undelivered messages; A4 digits stripped; A5 reworded prompt; DeepSeek | H20-H24 |
| `notice_checks` | `notice_n1_new_seeds.yaml`, `notice_n2_mixed_luna.yaml` | N1 notice on new seeds; N2 notice in DeepSeek x Luna | H27, H28 |

Smoke configs: `channel_tiny_c1.yaml`, `notes_deepseek_tiny_*.yaml`, `workspace_tiny_luna_*.yaml`, `placebo_tiny.yaml`,
`narrow_costs_tiny_*.yaml`, `ext_tiny.yaml`, `ext_tiny_n3.yaml`, `luna_long_tiny.yaml`, `lunarep_tiny.yaml`,
`abl_a*_tiny.yaml`, `notice_n*_tiny.yaml`.

## Earlier runs (exploratory, before any declaration)

| Run id | Config(s) | What |
|---|---|---|
| `pilot` | `pilot.yaml` | Three models x three tie-break rules, three firms, 25 rounds |
| `rotation_screen` | `rotation_screen_*.yaml` | Settings that might produce rotation under the random tie-break |
| `n2_replicate` | `supporting_n2_replicate.yaml` | Replication of the screen's one high DeepSeek session |
| `common_cost_check` | `common_cost_check.yaml` | Harness check of the common-cost draw |
| `costrange` | `supporting_costrange.yaml` | Costs within 10 of each other in a round |
| `costs_revealed` | `supporting_costs_revealed.yaml` | Every firm sees every cost |
| `workspace_screen_n2` | `workspace_screen_n2.yaml` | First shared-notes screen |
| `private_screen_n2` | `workspace_screen_n2_private.yaml` | First private-notes screen, DeepSeek |

Harness checks with no API calls: `sanity_dummy.yaml` (scripted bidders, expected index readings) and
`sanity_tiebreak.yaml`. End-to-end check before the first live call: `pilot_tiny.yaml`, then `channel_tiny.yaml` and
`workspace_tiny.yaml` for the channel and notes code.

## Not run

| Config | Why |
|---|---|
| `main_tiebreak.yaml`, `supporting_info.yaml`, `supporting_lineup.yaml`, `supporting_n.yaml` | The shelved tie-break design; the runner refuses them (thinking mode and output cap unset) |
| `channel_screen_n2.yaml` | First message-channel screen; replaced by the declared `channel_c1.yaml` |
