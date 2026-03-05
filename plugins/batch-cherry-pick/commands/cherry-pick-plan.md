# /cherry-pick-plan

Plan a batch cherry-pick operation: analyze commits, detect already-applied ones, and build a TODO list.

## Usage

```
/cherry-pick-plan <source> [--onto <branch>]
```

**Source formats:**
- Branch range: `branch1..branch2`
- Space-separated hashes: `abc1234 def5678 ghi9012`
- File reference: `@commits.txt` (one hash per line)
- Single branch: `feature/upstream` (all commits not on target)

**Options:**
- `--onto <branch>`: Target branch (default: current branch)

## Instructions

You are executing the `/cherry-pick-plan` command. Follow these steps precisely:

### Step 1: Parse Arguments

Extract from the user's input:
- **source**: The commit source (branch range, hashes, or file reference)
- **target_branch**: From `--onto` flag, or default to current branch name

If the source is unclear, ask the user to clarify.

### Step 2: Validate Repository State

Run these checks:
```bash
# Ensure we're in a git repo
git rev-parse --git-dir

# Check for clean working tree
git status --porcelain

# Check no cherry-pick already in progress
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"

# Check no existing batch state (or confirm overwrite)
test ! -f "$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

If working tree is dirty, warn the user and ask them to commit or stash changes first.
If an existing state file exists, show its status summary and ask the user if they want to overwrite.

### Step 3: Resolve Commits

Based on the source format:

**Branch range** (`A..B`):
```bash
git log --reverse --format="%H %h %an <%ae> %s" A..B
```

**Space-separated hashes**: Resolve each individually:
```bash
git log -1 --format="%H %h %an <%ae> %s" <hash>
```

**File reference** (`@file.txt`): Read the file, resolve each hash.

**Single branch**: Commits on source not on target:
```bash
git log --reverse --format="%H %h %an <%ae> %s" <target>..<source>
```

For each commit, also check:
```bash
# Is it a merge commit?
git cat-file -p <hash> | grep -c "^parent" # >1 means merge
```

### Step 4: Detect Already-Applied Commits

For each commit, run the detection script:
```bash
bash plugins/batch-cherry-pick/scripts/detect-already-applied.sh <hash> <target_branch>
```

Or use inline equivalent: search for cherry-pick trailers and compare patch-ids.

### Step 5: Enable git rerere

```bash
git config rerere.enabled true
```

Tell the user this was done (helps with repeated conflict patterns).

### Step 6: Create State File

Write the state file to `.git/cherry-pick-batch.json` using this structure:

```json
{
  "version": 1,
  "created_at": "<ISO-timestamp>",
  "updated_at": "<ISO-timestamp>",
  "source": "<user-provided source string>",
  "target_branch": "<branch>",
  "original_head": "<current HEAD hash>",
  "conflict_mode": "manual",
  "post_resolution_mode": "wait-for-review",
  "commits_processed_this_session": 0,
  "commits": [
    {
      "hash": "<full-sha>",
      "short_hash": "<7-char>",
      "subject": "<first line of commit message>",
      "author": "<Name <email>>",
      "status": "pending",
      "is_merge_commit": false,
      "already_applied": false,
      "cherry_pick_hash": null,
      "conflict_files": [],
      "auto_resolve_attempts": 0,
      "review_details": {
        "coder_a_verdict": null,
        "coder_b_verdict": null,
        "leader_decision": null,
        "issues": []
      },
      "skipped_reason": null
    }
  ],
  "current_index": 0,
  "stats": { "total": <N>, "completed": 0, "skipped": 0, "failed": 0 }
}
```

Mark any already-applied commits with `"already_applied": true`.

### Step 7: Display Plan Table

Show the user a clear table:

```
## Cherry-Pick Plan

Source: <source>
Target: <target_branch>
Total commits: <N> (<M> already applied)

| # | Hash    | Author         | Subject                          | Status          |
|---|---------|----------------|----------------------------------|-----------------|
| 1 | abc1234 | Alice          | Add feature X                    | pending         |
| 2 | def5678 | Bob            | Fix bug Y                        | already-applied |
| ...                                                                                  |
```

### Step 8: Ask User Preferences

Present these options:
1. **Conflict mode**: `manual` (default) or `auto` - Auto attempts AI-driven conflict resolution
2. **Post-resolution mode**: `wait-for-review` (default) or `auto-continue` - Whether to pause after each commit

**Defaults are manual + wait-for-review.** The user must explicitly opt into auto modes.

Also tell the user:
- They can **remove** commits from the plan (give the `#` to remove)
- They can **reorder** commits (specify new order)
- They can **add** more commits

### Step 9: Suggest Next Step

After the user confirms the plan:
> Plan saved. Run `/cherry-pick-start` to begin cherry-picking.
