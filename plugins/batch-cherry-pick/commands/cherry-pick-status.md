# /cherry-pick-status

Show progress of the current batch cherry-pick operation.

## Usage

```
/cherry-pick-status [--verbose]
```

**Options:**
- `--verbose`: Show full details for each commit including review results

## Instructions

You are executing the `/cherry-pick-status` command. Follow these steps:

### Step 1: Load State File

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
cat "$STATE_FILE"
```

If no state file exists, tell the user:
> No batch cherry-pick in progress. Run `/cherry-pick-plan` to create a plan.

### Step 2: Detect State Issues

Check for potential problems:

```bash
# Check if we're on the expected branch
CURRENT_BRANCH=$(git branch --show-current)
# Compare with state's target_branch

# Check if HEAD has drifted (someone committed outside the batch)
CURRENT_HEAD=$(git rev-parse HEAD)
# Compare with expected position

# Check if a cherry-pick is in progress but not recorded
test -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"
```

Report any discrepancies to the user.

### Step 3: Display Progress Summary

Show a concise summary:

```
## Batch Cherry-Pick Status

Source: <source>
Target: <target_branch>
Mode: conflict=<manual|auto>, post-resolution=<wait-for-review|auto-continue>
Session commits: <commits_processed_this_session>

### Progress: <completed>/<total> (<percentage>%)

| # | Hash    | Author         | Subject                          | Status      |
|---|---------|----------------|----------------------------------|-------------|
| 1 | abc1234 | Alice          | Add feature X                    | completed   |
| 2 | def5678 | Bob            | Fix bug Y                        | skipped     |
| 3 | ghi9012 | Charlie        | Refactor Z                       | in-progress |
| 4 | jkl3456 | Alice          | Update docs                      | pending     |

Completed: <N> | Skipped: <N> | Failed: <N> | Remaining: <N>
```

Use status indicators:
- `completed` - Successfully cherry-picked
- `skipped` - Skipped (show reason if available)
- `in-progress` - Currently being processed
- `conflict` - Has unresolved conflicts
- `reviewing` - Under multi-agent review
- `failed` - Cherry-pick failed
- `pending` - Not yet attempted
- `already-applied` - Detected as already on target (show for `already_applied: true`)

### Step 4: Verbose Mode

If `--verbose` is requested, also show for each non-pending commit:
- Cherry-pick result hash (if completed)
- Conflict files (if any)
- Review verdicts from CoderA/CoderB
- Skip/failure reasons

### Step 5: Suggest Next Action

Based on current state, suggest what to do next:
- If a commit is `in-progress` or `conflict`: suggest `/cherry-pick-resolve` or `/cherry-pick-skip`
- If all pending and ready: suggest `/cherry-pick-next`
- If all done: congratulate and suggest verifying with `git log`
- If `commits_processed_this_session` >= 5: remind about `/compact`
