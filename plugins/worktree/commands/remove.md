# /worktree:remove

Remove a git worktree by branch name or path, with safety checks for uncommitted changes.

## Usage

```
/worktree:remove <branch-or-path>
```

## Instructions

You are executing the `/worktree:remove` command. Follow these steps precisely:

### Step 1: Validate

```bash
# Ensure we're in a git repo
git rev-parse --git-dir

# List all worktrees for matching
git worktree list --porcelain
```

If not in a git repo, tell the user and stop.

### Step 2: Match Worktree

The user provides either a branch name or a path. Match it against the worktree list:

```bash
# Try matching as a path (exact or partial match)
git worktree list --porcelain | grep "^worktree"

# Try matching as a branch name
git worktree list --porcelain | grep "^branch refs/heads/<branch-or-path>"
```

Parse the porcelain output to find the worktree whose **path** matches the argument, or whose **branch** matches the argument.

If no match is found, tell the user:

> No worktree found matching "<branch-or-path>". Run `/worktree:list` to see available worktrees.

If the match is the **main worktree** (the first entry in `git worktree list`), warn the user:

> Cannot remove the main worktree. Use `git worktree move` if you need to relocate it.

Stop in either case.

### Step 3: Check for Uncommitted Changes

```bash
# Check for uncommitted changes in the target worktree
git -C "<worktree-path>" status --porcelain
```

If there are uncommitted changes, warn the user:

> WARNING: Worktree at <path> has uncommitted changes:
> <list of changed files>
>
> Remove anyway? This will discard these changes.

- **User says yes**: Proceed with `--force` in Step 4.
- **User says no**: Stop. Tell the user to commit or stash changes first.

### Step 4: Remove Worktree

```bash
# Remove the worktree (use --force if user confirmed despite dirty state)
git worktree remove "<worktree-path>"
# or with force:
git worktree remove --force "<worktree-path>"
```

If the remove fails, show the error. Common issue: the worktree is locked. In that case:

```bash
# Unlock first, then remove
git worktree unlock "<worktree-path>"
git worktree remove "<worktree-path>"
```

### Step 5: Ask About Branch Deletion

Determine the branch that was checked out in the removed worktree.

Ask the user:

> Worktree removed. Also delete the branch `<branch>`?

- **User says yes**: Delete the branch safely:
  ```bash
  git branch -d <branch>
  ```
  If `-d` fails (branch not fully merged), inform the user:
  > Branch `<branch>` is not fully merged. Force delete with `git branch -D <branch>`?

  - **User says yes**: `git branch -D <branch>`
  - **User says no**: Leave the branch.

- **User says no**: Leave the branch intact.

### Step 6: Report Result

```bash
# Confirm worktree is removed
git worktree list
```

Output a summary:

```
Worktree removed:
- Path: <path> (deleted)
- Branch: <branch> (deleted / kept)
```

### Important Notes

- NEVER remove the main worktree -- always check for this
- Always check for uncommitted changes before removing
- Use `git branch -d` (safe delete) first; only offer `-D` (force) if the safe delete fails
- Each question is a natural pause point; wait for the user's response before continuing
