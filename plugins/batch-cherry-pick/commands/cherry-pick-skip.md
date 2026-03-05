# /cherry-pick-skip

Skip the current commit in the batch cherry-pick plan.

## Usage

```
/cherry-pick-skip [reason]
```

**Arguments:**
- `reason` (optional): Why this commit is being skipped. Recorded in state file.

## Instructions

You are executing the `/cherry-pick-skip` command. Follow these steps:

### Step 1: Load State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

If no state file exists, tell the user there's no active batch.

### Step 2: Identify Current Commit

Get the commit at `current_index`. Show the user what will be skipped:
```
Skipping commit #<N>: <short_hash> <subject> (by <author>)
Reason: <reason or "no reason provided">
```

### Step 3: Abort In-Progress Cherry-Pick

If a cherry-pick is currently in progress (conflict state):
```bash
git cherry-pick --abort
```

This cleanly reverts any partial changes.

### Step 4: Update State

Update the commit entry:
```json
{
  "status": "skipped",
  "skipped_reason": "<user-provided reason or 'skipped by user'>"
}
```

Update stats:
```json
{
  "stats.skipped": "+1"
}
```

Increment `commits_processed_this_session`.

### Step 5: Post-Skip Behavior

**If `post_resolution_mode` is `wait-for-review`:**
- Show: "Commit skipped. Run `/cherry-pick-next` to continue."
- STOP

**If `post_resolution_mode` is `auto-continue`:**
- Automatically proceed to next pending commit
- Follow `/cherry-pick-next` protocol from Step 4 onwards
