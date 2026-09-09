# Portability contract

This repository has one portable core and host-specific installation
layers. The core is authoritative for workflow and design guidance; an
adapter may map that guidance onto a host's filenames, tools, and
lifecycle events, but must not redefine it.

## Portable core

Use the most widely implemented interface that fits the asset:

| Asset                          | Portable interface                                   | Contract                                                                                                 |
| ------------------------------ | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Reusable procedure             | [Agent Skills](https://agentskills.io/specification) | One directory per skill, with a conforming `SKILL.md` and optional local references, scripts, and assets |
| Deterministic local operation  | Command-line program                                 | Cross-platform where practical, explicit inputs and outputs, useful without a particular model host      |
| External or authenticated tool | MCP server                                           | Authentication and live data stay outside prose instructions                                             |
| Always-loaded guidance         | Canonical Markdown source                            | Host adapters install or expose the same guidance without maintaining independent copies                 |

The canonical user-skill destination is `~/.agents/skills`. Codex,
Gemini CLI, and GitHub Copilot discover that location. Claude Code
currently uses `~/.claude/skills`, so its adapter links the same source
directories there. The repository's installer writes both destinations,
along with a Claude import stub and a generated Codex instruction
snapshot from the same canonical guidance.

Project-specific instructions and skills remain in their project. This
repository owns only preferences and methods that hold across projects.

## Host support matrix

"Adapter" means that the capability is host-specific even when its
policy is shared. A new host should require a new adapter, not a fork of
the portable core.

| Capability                 | Portable boundary               | Claude Code                       | Codex                                     | Other hosts                                                                 |
| -------------------------- | ------------------------------- | --------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------- |
| User instructions          | Canonical Markdown              | `~/.claude/CLAUDE.md`             | `~/.codex/AGENTS.md`                      | Install at the host's user-instruction location                             |
| Project instructions       | Project-owned guidance          | `CLAUDE.md`                       | `AGENTS.md`                               | Prefer `AGENTS.md` when supported; otherwise add a thin host shim           |
| User skills                | Agent Skills directories        | `~/.claude/skills`                | `~/.agents/skills`                        | Prefer `~/.agents/skills` when supported                                    |
| Project skills             | Agent Skills directories        | `.claude/skills`                  | `.agents/skills`                          | Prefer `.agents/skills` when supported                                      |
| Lifecycle automation       | Shared policy behind an adapter | `settings.json` hooks             | Partial: not installed in this phase      | Host hook/extension API, when one exists                                    |
| Subagents and model choice | Semantic work classification    | Claude agent and model vocabulary | Codex agent and reasoning vocabulary      | Host capability map; never put product model names in the portable contract |
| Session analytics          | Normalized report input         | Claude transcript reader          | Versioned Codex reader when stable enough | Provider reader or an explicit unsupported result                           |
| Live integrations          | MCP                             | Supported                         | Supported                                 | MCP where available                                                         |

## Agent Skills profile

Every directory immediately below `skills/` must contain `SKILL.md`.
Each skill follows the open Agent Skills specification rather than
relying on a host extension:

- `name` is lowercase letters, digits, and single hyphens; it matches
  its directory and is at most 64 characters.
- `description` is non-empty, at most 1024 characters, and states both
  the capability and its trigger.
- `compatibility`, when present, is at most 500 characters and names
  runtime or host capabilities that are genuinely required.
- Supporting material stays inside the skill directory and is referenced
  by relative path.
- Non-standard host-specific frontmatter is excluded from the portable
  core.

Run `pixi run skills` to validate the mechanically enforceable part of
this profile. Activation quality remains a behavioral property and is
covered by the repository's existing description and evidence audits.

## Adapter rules

1. Preserve one semantic definition. Adapters translate paths, event
   schemas, tool names, and model vocabulary only.
2. Keep optional accelerators optional. A workflow may use Superpowers
   or a host review facility when installed, but must either declare
   that requirement or provide a fallback.
3. Fail visibly when a host cannot provide a capability. Do not report
   an installation or analytics check as passing when its provider is
   absent.
4. Preserve user-owned configuration. Installation remains idempotent,
   verifies links, and backs up real files before replacement.
5. Test each adapter against fixtures from its host. Similar event names
   do not imply identical input and output contracts.
