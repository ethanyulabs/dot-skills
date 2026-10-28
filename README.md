# dot-skills

A personal [Agent Skill](https://agentskills.io) for Claude Code, Codex and other coding agents: one skill, `dot`, with one subcommand per tool, invoked as `/dot <subcommand> <action> …` (Codex: `$dot <subcommand> …`). Installing `dot` once brings every subcommand.

## Install

Requires Node.js. Installs go through the [`skills`](https://github.com/vercel-labs/skills) CLI:

```bash
# pick agents interactively, install for the current user
npx skills add ethanyulabs/dot-skills -g

# install without prompts
npx skills add ethanyulabs/dot-skills -g --skill dot -y

# only list what the repo offers
npx skills add ethanyulabs/dot-skills --list

# later
npx skills update -g
```

## Subcommands

| Subcommand | What it does | Needs |
|---|---|---|
| [`dot photo`](skills/dot/photo/COMMAND.md) | Photo style processing, one photo or a whole folder: extract and apply a JSON style, portrait skin retouch that keeps texture, landscape depth, and print / web / dating-app exports. | [uv](https://docs.astral.sh/uv/) (dependencies download on first run) |

## Layout

The skill is `skills/dot/`; each subcommand is a directory inside it:

```
skills/dot/
├── SKILL.md             # frontmatter (name, description) + subcommand table + how to route
├── agents/              # agent-specific metadata (e.g. openai.yaml for Codex)
└── <subcommand>/
    ├── COMMAND.md       # the subcommand's entry: actions table, steps, "done when" (no frontmatter)
    ├── references/      # one file per action: inputs, steps, done when
    ├── scripts/         # a single entry point run with `uv run --script`, plus tests
    └── assets/          # presets, schemas, report templates
```

`SKILL.md` is a thin router: it picks the subcommand from the request and reads that subcommand's `COMMAND.md`. A subcommand directory never holds a `SKILL.md` of its own, because skill installers would treat it as a separate skill or shadow it.

To add a subcommand: create `skills/dot/<sub>/COMMAND.md` with its `references/`, `scripts/` and `assets/`; add a row to the table in `skills/dot/SKILL.md` and to the table above; add one sentence with its trigger words to the `description` in `skills/dot/SKILL.md` (the whole description must stay under 1024 characters); validate and run its tests.

Docs are written in English; user-facing reports are in Chinese.

## Home directory

A subcommand keeps the user's own things (saved presets, default parameters, outputs) under `~/.dot/<subcommand>/`, never next to the user's files: `dot photo` uses `~/.dot/photo/`. The environment variable `DOT_HOME` moves the `~/.dot` root, which is also how tests isolate themselves. Validate the skill with `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py skills/dot` and run a subcommand's tests with `uv run --script skills/dot/<subcommand>/scripts/run_tests.py`.

## License

MIT
