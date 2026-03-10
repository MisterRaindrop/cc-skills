# /worktree:list

List all git worktrees with branch, HEAD commit, and lock status in a readable table.

## Usage

```
/worktree:list
```

## Instructions

You are executing the `/worktree:list` command. Follow these steps precisely:

### Step 1: Validate

```bash
# Ensure we're in a git repo
git rev-parse --git-dir
```

If not in a git repo, tell the user and stop.

### Step 2: Gather Worktree Data

```bash
# Get porcelain output for reliable parsing
git worktree list --porcelain
```

The porcelain output format is:

```
worktree <path>
HEAD <commit-hash>
branch refs/heads/<branch-name>
<blank line>
```

Locked worktrees include an additional `locked` line (optionally with a reason: `locked <reason>`).
Detached HEADs show `detached` instead of `branch refs/heads/<name>`.

Parse each worktree block to extract:
1. **Path** -- the worktree directory
2. **Branch** -- the branch name (strip `refs/heads/` prefix), or `(detached)` if HEAD is detached
3. **HEAD** -- the short commit hash and subject line
4. **Locked** -- whether the worktree is locked (and the reason, if any)

For each worktree, get the commit subject:

```bash
git -C <path> log -1 --format="%h %s" 2>/dev/null
```

### Step 3: Present Results

Output a table:

```
| Path | Branch | HEAD | Locked |
|------|--------|------|--------|
| /path/to/main-worktree | main | a1b2c3d Fix bug in parser | No |
| /path/to/feature-wt | feature-x | e4f5g6h Add new endpoint | No |
| /path/to/hotfix-wt | hotfix-1 | i7j8k9l Patch security issue | Yes (reason) |
```

If there is only one worktree (the main one), note:

> Only the main worktree exists. Use `/worktree:create` to add more.

### Important Notes

- Always use `--porcelain` for reliable machine-parseable output
- Show absolute paths so the user can navigate directly
- Keep the table compact -- truncate long commit subjects if needed
- The main worktree (bare repo root) is always listed first
