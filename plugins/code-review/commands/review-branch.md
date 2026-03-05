# /review-branch

Review the diff between the current branch and a base branch.

## Usage

```
/review-branch <base-branch> [--depth quick|standard|deep] [--lang zh|en]
```

**Arguments:**
- `<base-branch>`: The branch to compare against (e.g., `main`, `develop`)

**Options:**
- `--depth`: Review depth (default: auto-detected based on change size)
- `--lang`: Output language override (default: auto-detected)

## Instructions

You are executing the `/review-branch` command. Follow these steps:

### Step 1: Parse Arguments

Extract the base branch name and options from user input.

If no branch provided, ask the user:
> Which branch should I compare against? (e.g., main, develop)

### Step 2: Validate Branch

```bash
# Check base branch exists
git rev-parse --verify <base-branch>

# Get current branch
CURRENT=$(git branch --show-current)

# Find merge base
MERGE_BASE=$(git merge-base HEAD <base-branch>)

# Count commits
COMMIT_COUNT=$(git log --oneline "$MERGE_BASE"..HEAD | wc -l)
```

If base branch doesn't exist, report the error and stop.

### Step 3: Show Review Target

```
## Reviewing Branch Diff

Current branch: <current-branch>
Base branch: <base-branch>
Merge base: <merge-base-short-hash>
Commits ahead: <N>

Commits included:
| Hash | Author | Subject |
|------|--------|---------|
| ... | ... | ... |

Total changes: <N> files, +<additions> -<deletions>
```

### Step 4: Collect Diff

```bash
DIFF_OUTPUT=$(bash plugins/code-review/scripts/collect-diff.sh branch <base-branch>)
```

### Step 5: Auto-Detect Depth

Same logic as `/review`. Respect `--depth` override.

### Step 6: Delete Previous State and Run Engine

```bash
bash plugins/code-review/scripts/review-state.sh delete 2>/dev/null || true
```

Follow the **review-engine** skill protocol with:
- `target.mode = "branch"`
- `target.branch = "<base-branch>"`

### Step 7: Present Results

Same result presentation as `/review`.
