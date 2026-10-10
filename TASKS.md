# agent-config Tasks

- [ ] **Consolidate the helpers duplicated across hooks.** Four hooks
  carry hand-kept copies of the same path and shell-parsing helpers, and
  the copies have already diverged:

  - `prose-writing.py`: `forward_slashed`, `resolve`, `canonical`,
    `without_heredocs`, `tokenize`, `shell_commands`, `destinations`,
    `written_paths`, `project_root`, `stamp_dir`, `EXCLUDED_PATHS`
  - `promotion-check.py`: `canonical`, `without_heredocs`, `tokenize`,
    `shell_commands`, `destinations`, `written_paths`
  - `audit-owed.py`: `without_heredocs`, `tokenize` (its copy alone
    retries without quotes), `shell_commands`
  - `prose-feedback.py`: `resolve`, `canonical`, `stamp_dir`,
    `EXCLUDED_PATHS` (it detects Bash writes from observed file changes,
    so it no longer carries the shell parser)

  Each hook's "keep the copies in step" comment says a shared module is
  impossible, because a hook runs standalone under whatever interpreter
  `~/.claude/settings.json` names. Test that premise first. When a hook
  runs as a script, `sys.path[0]` is its own directory, so a sibling
  module may already be importable. If it is, `register_hooks.py` must
  learn to skip a non-hook module in `hooks/`, since it registers every
  `hooks/*.py` and a test fails on a file with no event marker.
  `prose-feedback.py` already loads code from `scripts/` by path, which
  is a second option. Either way, reconcile the divergent copies to one
  behaviour on purpose, and replace the comments with one test that
  imports the shared helper from each hook. The `shlex`
  `punctuation_chars` merge of `);` and `)&&` into one token is a known
  flaw in every `shell_commands` copy, so fix it once there.
