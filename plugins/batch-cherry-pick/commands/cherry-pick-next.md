# /cherry-pick-next

Continue to the next commit in the batch cherry-pick plan.

## Usage

```
/cherry-pick-next [--force]
```

**Options:**
- `--force`: Proceed even if the previous commit is still in conflict/reviewing state

## Instructions

You are executing the `/cherry-pick-next` command. Follow these steps:

### Step 1: Load State and Validate

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

Validate:
1. State file exists
2. Working tree is clean
3. No cherry-pick in progress (no `CHERRY_PICK_HEAD`)

### Step 2: Check Previous Commit Status

Look at the commit at `current_index`:
- If status is `conflict` or `reviewing` and `--force` is NOT provided:
  - Warn: "Previous commit <hash> is still in state '<status>'. Use `--force` to skip ahead, or resolve it first with `/cherry-pick-resolve`."
  - STOP and wait for user instruction
- If `--force` is provided: mark previous as `skipped` with reason "force-skipped by user"

### Step 3: Context Management Check

Check the `commits_processed_this_session` counter:

- **Every 5 commits**: Display reminder:
  ```
  You've processed <N> commits this session. Consider running `/compact` to free up context.
  Current progress: <completed>/<total>
  ```

- **At 70%+ context usage** (if you can estimate): Recommend:
  ```
  Context usage is high. Recommend starting a new session.
  Your progress is saved -- just run `/cherry-pick-next` in a new session to resume.
  ```

### Step 4: Find Next Pending Commit

Advance `current_index` to the next commit with status `"pending"`.

Skip already-applied commits:
- If `already_applied: true`, confirm skip with user (or auto-skip if they previously approved)
- Update status to `"skipped"` with reason

If no more pending commits exist:
```
## Batch Cherry-Pick Complete!

All commits have been processed.
- Completed: <N>
- Skipped: <N>
- Failed: <N>

Run `/cherry-pick-status --verbose` for full details.
```
STOP here.

### Step 5: Execute Cherry-Pick

Follow the same cherry-pick execution protocol as in `/cherry-pick-start` Step 5:

1. Update commit status to `"in-progress"`
2. Execute `git cherry-pick -x <hash>` (or `-x -m 1` for merge commits)
3. Handle success/conflict/failure
4. Trigger review if applicable
5. Increment `commits_processed_this_session`

### Step 6: Post-Commit Behavior

Same as `/cherry-pick-start` Step 6:
- **wait-for-review mode**: Show result and STOP
- **auto-continue mode**: Proceed to next commit automatically (but pause every 5 commits)

### Important Notes

- The state file guarantees resume capability. If the user exits and comes back, `/cherry-pick-next` picks up where they left off.
- Always show a one-line progress indicator: `[<completed>/<total>] <hash> <subject> -- <result>`
- Keep output minimal for successful picks to preserve context window
