# /cherry-pick-resolve

After manually resolving conflicts, continue the cherry-pick and optionally trigger review.

## Usage

```
/cherry-pick-resolve [--no-review]
```

**Options:**
- `--no-review`: Skip the multi-agent review and mark as completed directly

## Instructions

You are executing the `/cherry-pick-resolve` command. Follow these steps:

### Step 1: Load State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

Verify the current commit is in `"conflict"` status.

### Step 2: Validate Resolution

Run thorough validation:

```bash
# Check no unmerged files remain
UNMERGED=$(git diff --name-only --diff-filter=U)
if [ -n "$UNMERGED" ]; then
  echo "Unmerged files still exist: $UNMERGED"
fi

# Check no conflict markers in staged files
bash plugins/batch-cherry-pick/scripts/validate-no-conflicts.sh

# Check git diff --check
git diff --check HEAD 2>/dev/null || true
```

If validation fails:
```
## Resolution Incomplete

The following issues were found:
- <list issues>

Please resolve all conflicts before running /cherry-pick-resolve again.
```
STOP and wait for user.

### Step 3: Stage and Continue Cherry-Pick

If there are unstaged resolved files, stage them:
```bash
git add -u
```

Then continue the cherry-pick:
```bash
git cherry-pick --continue
```

If `git cherry-pick --continue` fails, report the error to the user.

### Step 4: Record New Commit

```bash
NEW_HASH=$(git rev-parse HEAD)
```

Update state:
```
cherry_pick_hash: <NEW_HASH>
```

### Step 5: Trigger Review (or Skip)

**With `--no-review`:**
- Mark commit as `"completed"` directly
- Show: `[<N>/<total>] <hash> <subject> -- completed (review skipped)`

**Without `--no-review` (default):**
- Mark commit as `"reviewing"`
- Invoke the **cherry-pick-review** skill (see `skills/cherry-pick-review/SKILL.md`)
- The review skill will determine the final verdict

### Step 6: Post-Resolution Behavior

Same as other commands:
- **wait-for-review mode**: Show result and STOP
- **auto-continue mode**: Proceed to next commit

Increment `commits_processed_this_session`.
