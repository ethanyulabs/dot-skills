# Contributing to dot-skills

Notes for whoever edits the `dot` skill. Nothing here is read at runtime: the agent reads `skills/dot/SKILL.md`, then `skills/dot/<subcommand>/COMMAND.md` and the files it names.

## Layout rules

```
skills/dot/
├── SKILL.md             # frontmatter (name, description) + subcommand table + how to route
├── agents/              # agent-specific metadata (e.g. openai.yaml for Codex)
└── <subcommand>/
    ├── COMMAND.md       # the subcommand's entry: actions table, steps, "done when" (no frontmatter)
    ├── references/      # one file per action or action group, plus principles.md for what holds across actions
    ├── scripts/         # a single entry point run with `uv run --script`, plus tests
    └── assets/          # presets, schemas, report templates
```

- **One skill, `dot`.** `SKILL.md` is a thin router; its `description` carries one sentence and the trigger words of every subcommand.
- **A subcommand's entry is `COMMAND.md`, never `SKILL.md`.** The `skills` CLI (vercel-labs/skills) walks a skill container up to three levels deep and "a `SKILL.md` discovered at a shallower level shadows anything nested below it", so a nested `SKILL.md` could never be listed or installed on its own; renaming buys nothing there. Claude Code and Codex document only `<skills-dir>/<name>/SKILL.md` and say nothing about `SKILL.md` files inside a skill's directory, so the behaviour is undefined: an agent that does recurse would register `photo` and `arc` as separate skills with their own triggers, competing with the `dot` router. `COMMAND.md` also tells a reader at a glance that this is an entry inside a skill, not a skill.
- **`references/` stays flat: one file per action (`portrait.md`) or per action group (`spaces.md` covers spaces / tabs / open / attach / goto / close / sessions), plus `principles.md` for what holds across actions (Step 0, output contract, home directory, who decides what).** Make a subdirectory `references/<action>/` only when one action needs three or more files; leave the rest flat, do not migrate everything for symmetry. Do not group by feature across `references/` / `scripts/` / `assets/`: the single `uv run --script` entry point and the installer both depend on these top-level directories, and the Python code is already split by feature inside `scripts/<tool>_lib/`.
- **User data** lives under `~/.dot/<subcommand>/` (`DOT_HOME` moves the `~/.dot` root), never next to the user's files. Tests isolate themselves with `DOT_HOME`.
- Docs are written in English; user-facing reports are in Chinese (`assets/templates/report.zh-CN.md`).

## Adding a subcommand

1. Create `skills/dot/<sub>/COMMAND.md` with Usage, an Actions table, Steps and Done when; put its `references/`, `scripts/` and `assets/` beside it, and keep its user data under `~/.dot/<sub>/`. Do not put a `SKILL.md` in that directory (see Layout rules).
2. Add one row to the Subcommands table in `skills/dot/SKILL.md`, and one row to the table in `README.md`.
3. Add one sentence for it to the `description` in the `skills/dot/SKILL.md` frontmatter: at most 250 characters, with up to 8 trigger words; the whole description must stay under 1024 characters (the validator's limit).
4. Run the acceptance checks below.

## Acceptance

Common to every change:

1. `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py skills/dot` passes. The validator reads the `dot` SKILL.md, whose description carries every subcommand's sentence and triggers.
2. `uv run --script skills/dot/<sub>/scripts/run_tests.py` is green for every subcommand touched.

### photo

- One portrait and one landscape through `dphoto run`, their `compare.jpg` opened and judged with `references/review-checklist.md`, every export present, the report in Chinese with absolute paths.

### arc

- `run_tests.py` must be green without a real Arc.
- With Arc relaunched on the port (quit it completely first, then `open -a Arc --args --remote-debugging-port=9222`; the flag is ignored when an Arc instance is still running): `DOT_ARC_LIVE=1 uv run --script skills/dot/arc/scripts/run_tests.py -k live` is green, and a manual `open → snapshot → fill → click → screenshot → close` in the user's agent space leaves their active space and tab untouched (last done 2026-10-28 on Arc 1.152 / Chrome 149).
