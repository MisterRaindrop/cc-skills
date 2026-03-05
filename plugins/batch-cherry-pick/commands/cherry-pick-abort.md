# /cherry-pick-abort

Abort the batch cherry-pick operation.

## Usage

```
/cherry-pick-abort [--reset]
```

**Options:**
- `--reset`: Reset to the original HEAD, undoing ALL completed cherry-picks. **Requires double confirmation.**

## Instructions

You are executing the `/cherry-pick-abort` command. Follow these steps:

### Step 1: Load State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

If no state file exists, also check if a git cherry-pick is in progress:
```bash
test -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"
```
If so, offer to run `git cherry-pick --abort`.

### Step 2: Show Current Progress

Before aborting, show what will be affected:

```
## Abort Batch Cherry-Pick

Current progress:
- Completed: <N> commits successfully cherry-picked
- In-progress: <current commit info if any>
- Remaining: <N> pending commits

Original HEAD: <original_head>
Current HEAD: <current HEAD>
```

### Step 3: Handle --reset Flag

**Without `--reset` (default):**
- Abort any in-progress cherry-pick: `git cherry-pick --abort` (if CHERRY_PICK_HEAD exists)
- Keep all completed cherry-picks
- Mark remaining pending commits as `"skipped"` with reason `"batch aborted"`
- Preserve the state file for reference

Tell the user:
```
Batch aborted. <N> completed cherry-picks have been kept.
State file preserved at .git/cherry-pick-batch.json for reference.
To start fresh, run /cherry-pick-plan again.
```

**With `--reset`:**
This is a destructive operation. Require DOUBLE confirmation:

1. First warning:
```
WARNING: --reset will undo ALL <N> completed cherry-picks by resetting to <original_head>.
This is destructive and cannot be undone.
Are you sure? (yes/no)
```

2. Second confirmation:
```
FINAL CONFIRMATION: This will run 'git reset --hard <original_head>'.
All cherry-picked commits will be lost. Type 'RESET' to confirm.
```

Only proceed if the user confirms both times. Then:
```bash
git cherry-pick --abort 2>/dev/null || true
git reset --hard <original_head>
```

Mark all commits as `"skipped"` with reason `"batch aborted with reset"`.

### Step 4: Clean Up

- If not --reset: keep state file, mark batch as aborted
- If --reset: keep state file as record, but add `"aborted": true` field

Do NOT delete the state file -- it serves as a record of what was attempted.

### Important Notes

- NEVER run `git reset --hard` without explicit double confirmation from the user
- Always abort any in-progress cherry-pick first before resetting
- The state file is preserved so the user can review what happened
