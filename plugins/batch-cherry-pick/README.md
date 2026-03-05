# Batch Cherry-Pick Plugin

Selectively cherry-pick commits from one branch to another with conflict handling, multi-agent review, and cross-session resume support.

## What is this?

When you have a branch with many commits and need to selectively port some of them to another branch, this plugin gives you a structured workflow: plan which commits to pick, execute them one by one with AI-assisted conflict resolution, and review each result before moving on. Your progress is saved automatically, so you can stop and resume at any time.

## Prerequisites

- **git** (required)
- **jq** (required) -- for state file management
- **Codex CLI** (optional) -- enables dual-reviewer mode. Without it, review falls back to Claude-only (single reviewer).

## Quick Start

```
# 1. Plan: analyze commits and build a TODO list
/cherry-pick-plan feature/upstream --onto main

# 2. Review the plan, adjust if needed, then start
/cherry-pick-start

# 3. After each commit, continue to the next
/cherry-pick-next

# 4. If a conflict occurs, resolve it and continue
/cherry-pick-resolve

# 5. Check progress at any time
/cherry-pick-status
```

## Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/cherry-pick-plan` | `<source> [--onto <branch>]` | Analyze commits and create a cherry-pick plan |
| `/cherry-pick-start` | `[--conflict-mode auto\|manual] [--post-resolution auto-continue\|wait-for-review]` | Begin executing the plan |
| `/cherry-pick-next` | `[--force]` | Continue to the next commit |
| `/cherry-pick-skip` | `[reason]` | Skip the current commit |
| `/cherry-pick-resolve` | `[--no-review]` | After resolving conflicts, continue and review |
| `/cherry-pick-status` | `[--verbose]` | Show progress and suggest next action |
| `/cherry-pick-abort` | `[--reset]` | Abort the batch (--reset undoes all picks) |

## Workflow

```
/cherry-pick-plan         /cherry-pick-start        /cherry-pick-next
      |                         |                         |
      v                         v                         v
 +---------+    confirm    +---------+   success   +---------+
 |  Plan   | -----------> | Execute | -----------> | Review  |
 | commits |              | commit  |              | commit  |
 +---------+              +---------+              +---------+
                               |                       |
                          conflict                approved
                               |                       |
                               v                       v
                          +---------+             +---------+
                          | Resolve |             |  Next   |
                          | conflict|             | commit  |
                          +---------+             +---------+
                               |
                     /cherry-pick-resolve
                     /cherry-pick-skip
```

## Modes

| Setting | Option | Description |
|---------|--------|-------------|
| Conflict mode | `manual` (default) | Report conflicts, wait for you to resolve |
| | `auto` | AI attempts resolution (falls back to manual after 3 failures) |
| Post-resolution | `wait-for-review` (default) | Pause after each commit for your review |
| | `auto-continue` | Automatically proceed (pauses on conflicts and every 5 commits) |

## FAQ

**What if I lose my session or close the terminal?**
Your progress is saved in `.git/cherry-pick-batch.json`. Start a new session and run `/cherry-pick-status` to see where you left off, then `/cherry-pick-next` to resume.

**What if Codex CLI is not installed?**
The plugin works without Codex. Review falls back to Claude-only mode (single reviewer). You'll see a warning when review runs. For dual-reviewer mode, install Codex CLI.

**How do I abort and undo everything?**
`/cherry-pick-abort` stops the batch but keeps completed picks. `/cherry-pick-abort --reset` undoes everything (requires double confirmation).

**Can I add or remove commits from the plan?**
Yes, during the `/cherry-pick-plan` step you can add, remove, or reorder commits before starting.

**What does the `-x` flag do?**
All cherry-picks use `git cherry-pick -x` which adds a "cherry picked from commit ..." trailer to the commit message. This makes it easy to trace where the commit came from.
