# /cherry-pick-start

Begin executing the batch cherry-pick plan.

## Usage

```
/cherry-pick-start [--conflict-mode auto|manual] [--post-resolution auto-continue|wait-for-review]
```

**Options:**
- `--conflict-mode`: Override conflict handling mode (default: manual)
- `--post-resolution`: Override post-resolution behavior (default: wait-for-review)

## Instructions

You are executing the `/cherry-pick-start` command. Follow these steps:

### Step 1: Load and Validate State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

If no state file exists, tell the user to run `/cherry-pick-plan` first.

Validate:
1. Current branch matches `target_branch` in state
2. Current HEAD matches `original_head` or the expected position after completed picks
3. Working tree is clean (`git status --porcelain`)
4. No cherry-pick already in progress

### Step 2: Apply Mode Overrides

If the user provided `--conflict-mode` or `--post-resolution` flags, update the state file:

```bash
# Example using state-update.sh
bash plugins/batch-cherry-pick/scripts/state-update.sh '.conflict_mode = "auto"'
```

**Default modes are manual + wait-for-review.** Only change if user explicitly requests.

### Step 3: Reset Session Counter

```bash
bash plugins/batch-cherry-pick/scripts/state-update.sh '.commits_processed_this_session = 0'
```

### Step 4: Show Starting Summary

```
## Starting Batch Cherry-Pick

Target: <target_branch>
Commits: <total> (<completed> already done, <remaining> remaining)
Conflict mode: <manual|auto>
Post-resolution: <wait-for-review|auto-continue>

Starting with commit #<current_index + 1>: <short_hash> <subject>
```

### Step 5: Process First Pending Commit

Find the first commit with `status: "pending"` (skip already-applied commits after confirming with user).

For already-applied commits:
- Show the user: "Commit <hash> (<subject>) appears to already be applied. Skipping."
- Update status to `"skipped"` with reason `"already applied"`
- Continue to next pending commit

For the first real pending commit, follow the **cherry-pick-batch** skill protocol:

1. **Pre-flight checks**: clean tree, commit exists, not already applied
2. **Execute cherry-pick**:
   - Regular commit: `git cherry-pick -x <hash>`
   - Merge commit: `git cherry-pick -x -m 1 <hash>`
   - If the commit is empty: ask user to skip or `--allow-empty`
3. **Handle result**:
   - **Success**: Update state (`status: "completed"`, record `cherry_pick_hash`), trigger review if in wait-for-review mode
   - **Conflict**: Update state (`status: "conflict"`, record `conflict_files`), handle based on conflict_mode
   - **Failure**: Update state (`status: "failed"`), report to user

### Step 6: Post-Commit Behavior

**If `post_resolution_mode` is `wait-for-review` (default):**
- After successful cherry-pick + review: show result and STOP
- Tell the user: "Commit <hash> applied successfully. Run `/cherry-pick-next` to continue, or `/cherry-pick-status` to see progress."

**If `post_resolution_mode` is `auto-continue`:**
- After successful cherry-pick + review: automatically proceed to next commit
- But still pause on conflicts (unless conflict_mode is auto)
- Always pause after every 5 commits for a context management check

### Important Notes

- ALWAYS use `git cherry-pick -x` (the `-x` flag is mandatory for traceability)
- For merge commits, ALWAYS use `-m 1` to select the first parent
- Increment `commits_processed_this_session` after each commit
- If `commits_processed_this_session` reaches 5, remind the user about `/compact`
