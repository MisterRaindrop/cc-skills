# /cherry-pick:batch

Batch cherry-pick multiple commits with TODO tracking, per-commit interactive flow, and optional full-auto mode.

## Usage

```
/cherry-pick:batch <source> [--onto <branch>] [--auto]
```

**Source formats:**
- Branch range: `branch1..branch2`
- Space-separated hashes: `abc1234 def5678 ghi9012`
- File reference: `@commits.txt` (one hash per line)
- Single branch: `feature/upstream` (all commits not on target)

**Options:**
- `--onto <branch>`: Target branch (default: current branch)
- `--auto`: Full automatic mode — auto-resolve conflicts, auto-review, auto-commit, auto-continue. Only pauses on failures.

## Instructions

You are executing the `/cherry-pick:batch` command. Follow these steps precisely:

### Step 1: Check for Existing State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

If state file exists, show its summary and ask:

> Found an existing batch cherry-pick in progress (<completed>/<total> done). Resume or start fresh?

- **Resume**: Load state, skip to Step 7 (continue from where it left off)
- **Start fresh**: Delete old state, continue to Step 2

### Step 2: Validate Repository

```bash
git rev-parse --git-dir
git status --porcelain
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"
```

If dirty, warn and stop.

### Step 3: Resolve Commits

Based on source format:

**Branch range** (`A..B`):
```bash
git log --reverse --format="%H %h %an <%ae> %s" A..B
```

**Space-separated hashes**: Resolve each:
```bash
git log -1 --format="%H %h %an <%ae> %s" <hash>
```

**File reference** (`@file.txt`): Read file, resolve each hash.

**Single branch**: Commits on source not on target:
```bash
git log --reverse --format="%H %h %an <%ae> %s" <target>..<source>
```

For each commit, detect merge commits:
```bash
git cat-file -p <hash> | grep -c "^parent"
```

### Step 4: Detect Already-Applied Commits

For each commit, check if already on target:
```bash
# Check cherry-pick trailer
git log --grep="cherry picked from commit <hash>" --oneline <target_branch>

# Compare patch-id
git show <hash> | git patch-id
```

### Step 5: Enable git rerere

```bash
git config rerere.enabled true
```

### Step 6: Create State and Show Plan

Write state file to `.git/cherry-pick-batch.json`:

```json
{
  "version": 2,
  "created_at": "<ISO-timestamp>",
  "updated_at": "<ISO-timestamp>",
  "source": "<user-provided source string>",
  "target_branch": "<branch>",
  "original_head": "<current HEAD hash>",
  "auto_mode": false,
  "commits_processed_this_session": 0,
  "commits": [
    {
      "hash": "<full-sha>",
      "short_hash": "<7-char>",
      "subject": "<first line>",
      "author": "<Name <email>>",
      "status": "pending",
      "is_merge_commit": false,
      "already_applied": false,
      "cherry_pick_hash": null,
      "conflict_files": [],
      "review_details": null,
      "skipped_reason": null
    }
  ],
  "current_index": 0,
  "stats": { "total": 0, "completed": 0, "skipped": 0, "failed": 0 }
}
```

Set `auto_mode: true` if `--auto` flag was provided.
Mark already-applied commits with `"already_applied": true`.

Show the plan:

```
## Batch Cherry-Pick Plan

Source: <source>
Target: <target_branch>
Mode: <interactive | auto>
Total: <N> commits (<M> already applied)

| # | Hash    | Author  | Subject                  | Status  |
|---|---------|---------|--------------------------|---------|
| 1 | abc1234 | Alice   | Add feature X            | pending |
| 2 | def5678 | Bob     | Fix bug Y                | applied |
| ...

Ready to start? You can also adjust the list (remove/reorder commits).
```

Wait for user confirmation. User may adjust the list before confirming.

### Step 7: Execute Commits

Process each pending commit in order. For each commit:

**Skip already-applied:**
- Show: `[N/total] <hash> <subject> — skipped (already applied)`
- Update state: `status: "skipped"`, `skipped_reason: "already applied"`

**Process pending commit:**

Follow the same flow as `/cherry-pick:commit` (cherry-pick → conflict handling → review → commit), with these batch-specific behaviors:

**Interactive mode (default):**
- Each step asks the user (auto-resolve? review? commit?)
- After each commit completes, ask: "Continue to next commit?"
  - User says "continue/next/yes" → process next
  - User says "skip" → mark skipped, move to next
  - User says "status" → show progress table, then ask again
  - User says "stop/abort" → stop processing, keep progress

**Auto mode (`--auto`):**
- Auto-resolve conflicts (AI-driven)
- Auto-run review
- If review APPROVED → auto-commit → auto-continue
- If review REJECTED or auto-resolve fails → **PAUSE** and ask user
- Show one-line progress per commit: `[N/total] <hash> <subject> — completed`

**State updates after each commit:**
```bash
# Update the state file with new status, cherry_pick_hash, etc.
# Increment commits_processed_this_session
# Update stats
```

### Step 8: Context Management

**Every 5 commits**, show:
```
--- Processed 5 commits this session. Consider /compact to free context. ---
Progress: <completed>/<total>
```

**When all commits are done:**
```
## Batch Cherry-Pick Complete!

Completed: <N> | Skipped: <N> | Failed: <N>

Run `git log --oneline -<total>` to verify.
```

### Step 9: Abort Handling

If the user says "abort" or "stop" at any point:

1. If a cherry-pick is in progress: `git cherry-pick --abort`
2. Mark remaining as `"skipped"` with reason `"batch aborted"`
3. Keep completed cherry-picks
4. Preserve state file

If the user explicitly asks to reset everything (undo all picks):
- Require double confirmation
- `git reset --hard <original_head>`
- This is destructive — be very clear about consequences

### Important Notes

- ALWAYS use `-x` flag (traceability)
- For merge commits, use `-m 1`
- State file enables cross-session resume
- `--auto` is opt-in; default is always interactive
- In auto mode, NEVER force through failures — always pause for user
