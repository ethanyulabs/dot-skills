# dot-skills

A personal collection of [Agent Skills](https://agentskills.io) for Claude Code, Codex and other coding agents. Every skill is named with a `dot-` prefix and invoked as `/dot-<name> <action>` (Codex: `$dot-<name> …`).

## Install

Requires Node.js. Installs go through the [`skills`](https://github.com/vercel-labs/skills) CLI:

```bash
# pick skills and agents interactively, install for the current user
npx skills add ethanyulabs/dot-skills -g

# install one skill without prompts
npx skills add ethanyulabs/dot-skills -g --skill dot-photo -y

# only list what the repo offers
npx skills add ethanyulabs/dot-skills --list

# later
npx skills update -g
```

## Skills

| Skill | What it does | Needs |
|---|---|---|
| [`dot-photo`](skills/dot-photo/SKILL.md) | Photo style processing: extract and apply a JSON style, portrait skin retouch that keeps texture, landscape depth, and print / web / dating-app exports. | [uv](https://docs.astral.sh/uv/) (dependencies download on first run) |

## Layout

Each skill lives in its own directory under `skills/`:

```
skills/<name>/
├── SKILL.md         # frontmatter (name, description) + actions table, steps, "done when"
├── references/      # one file per action: inputs, steps, done when
├── scripts/         # a single entry point run with `uv run --script`, plus tests
├── assets/          # presets, schemas, report templates
└── agents/          # agent-specific metadata (e.g. openai.yaml for Codex)
```

Docs are written in English; user-facing reports are in Chinese. Validate a skill with `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py skills/<name>` and run its tests with `uv run --script skills/<name>/scripts/run_tests.py`.

## License

MIT
