# /worktree:create

Create a new git worktree with smart defaults for path and branch handling.

## Usage

```
/worktree:create <branch> [--path <dir>] [--base <base-branch>]
```

## Instructions

You are executing the `/worktree:create` command. Follow these steps precisely:

### Step 1: Validate

```bash
# Ensure we're in a git repo
git rev-parse --git-dir

# Get repo root and name
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")

# Get current branch (used as default base)
CURRENT_BRANCH=$(git branch --show-current)
```

If not in a git repo, tell the user and stop.

### Step 2: Determine Worktree Path

If the user provided `--path <dir>`, use that as the worktree path.

If no `--path` was provided, compute the default:

```bash
# Default path: sibling directory named <repo-name>-<branch>
WORKTREE_PATH="$REPO_ROOT/../$REPO_NAME-<branch>"
```

Resolve the path to an absolute path and check it doesn't already exist:

```bash
# Ensure target path doesn't already exist
if [ -d "$WORKTREE_PATH" ]; then
  echo "ERROR: Directory already exists: $WORKTREE_PATH"
fi
```

If the path already exists, warn the user and stop.

### Step 3: Check Branch and Create Worktree

Determine the base branch: if the user provided `--base <base-branch>`, use that; otherwise default to the current branch.

Check whether the branch already exists:

```bash
# Check if branch exists (local or remote)
git show-ref --verify --quiet "refs/heads/<branch>" 2>/dev/null
```

**Branch exists:**

```bash
git worktree add "$WORKTREE_PATH" <branch>
```

**Branch does not exist:**

```bash
# Create new branch from base and set up worktree
git worktree add -b <branch> "$WORKTREE_PATH" <base-branch>
```

If the git command fails, show the error and stop.

### Step 4: Report Result

Show the user what was created:

```bash
# Confirm the worktree was created
git worktree list

# Show branch info for the new worktree
git -C "$WORKTREE_PATH" log -1 --oneline
```

Output a summary:

```
Worktree created:
- Path: <absolute-path>
- Branch: <branch>
- Base: <base-branch> (only if new branch was created)
- HEAD: <short-hash> <subject>
```

### Important Notes

- Always resolve the worktree path to an absolute path before creating
- If the branch already exists on a remote but not locally, `git worktree add` will auto-track it
- Do NOT `cd` into the new worktree automatically -- just report the path so the user can decide
- Keep output concise: path, branch, and HEAD summary
