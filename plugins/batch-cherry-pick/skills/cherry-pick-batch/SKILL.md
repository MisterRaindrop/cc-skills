# Cherry-Pick Batch Skill - Core Orchestration

This is the core execution engine for the batch cherry-pick workflow. It handles the actual cherry-pick execution, conflict resolution, edge cases, and context management.

## When This Skill is Used

This skill is invoked internally by the commands (`/cherry-pick-start`, `/cherry-pick-next`). It is NOT directly triggered by the user.

## State File Location

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

All state reads use `scripts/state-read.sh` and writes use `scripts/state-update.sh`.

---

## Cherry-Pick Execution Protocol

### Pre-flight Checks

Before each cherry-pick, verify:

```bash
# 1. Clean working tree
test -z "$(git status --porcelain)"

# 2. No cherry-pick already in progress
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"

# 3. Commit exists and is reachable
git cat-file -t <hash>

# 4. Check if already applied
bash plugins/batch-cherry-pick/scripts/detect-already-applied.sh <hash>
```

If already applied: ask user to confirm skip, then mark `skipped` with reason `"already applied"`.

### Execute Cherry-Pick

**CRITICAL: Always use `-x` flag for traceability.**

```bash
# Regular commit
git cherry-pick -x <hash>

# Merge commit (select first parent)
git cherry-pick -x -m 1 <hash>
```

**Handle results:**

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | Success | Proceed to post-validation |
| 1 | Conflict | Enter conflict handling |
| 128 | Fatal error | Mark failed, report to user |

**Empty commit handling:**
If git reports "nothing to commit", ask the user:
> Commit <hash> (<subject>) produces an empty cherry-pick. Options:
> 1. Skip it (`/cherry-pick-skip empty commit`)
> 2. Keep it with `--allow-empty`

### Post-Validation

After successful cherry-pick:

```bash
# Verify no conflict markers leaked through
bash plugins/batch-cherry-pick/scripts/validate-no-conflicts.sh

# Record the new commit hash
git rev-parse HEAD
```

Update state:
```
status: "completed" (or "reviewing" if review is triggered)
cherry_pick_hash: <new HEAD>
```

---

## Conflict Handling

### Identify Conflicts

```bash
# List conflicted files
git diff --name-only --diff-filter=U

# Show conflict details
git diff --name-only --diff-filter=U | while read f; do
  echo "--- $f ---"
  grep -n '<<<<<<<\|=======\|>>>>>>>' "$f" | head -10
done
```

### Manual Mode (Default)

Report the conflicts clearly to the user:

```
## Conflict in commit <short_hash>: <subject>

Conflicted files:
- path/to/file1.ext (lines 42-58)
- path/to/file2.ext (lines 10-25)

Original commit intent:
<Show the original commit's diff summary so user understands what the commit was trying to do>

Options:
1. Resolve manually, then run `/cherry-pick-resolve`
2. Skip this commit with `/cherry-pick-skip`
3. Abort the batch with `/cherry-pick-abort`
```

Update state: `status: "conflict"`, `conflict_files: [...]`

STOP and wait for the user.

### Auto Mode

When `conflict_mode: "auto"`, attempt intelligent resolution:

**Step 1: Analyze conflicts**
```bash
# Get the original commit's changes
git show <original-hash> --stat
git show <original-hash> -- <conflicted-file>

# Get the conflict content
cat <conflicted-file>  # Shows conflict markers
```

**Step 2: Attempt resolution**

For each conflicted file:
1. Read the conflict markers
2. Read the original commit's change to understand intent
3. Read the current state of the file on the target branch
4. Apply intelligent merge:
   - **Additive changes** (new functions, new imports): Keep both sides
   - **Modification conflicts**: Prefer the cherry-picked version if it's a clear update; ask user if ambiguous
   - **Deletion conflicts**: Flag for user review

**Step 3: Validate and stage**
```bash
# After resolving, verify no markers remain
bash plugins/batch-cherry-pick/scripts/validate-no-conflicts.sh

# Stage resolved files
git add <resolved-files>
```

**Step 4: Track attempts**

Increment `auto_resolve_attempts` for the commit. After **3 failed attempts**, automatically switch to manual mode:

```
Auto-resolution failed after 3 attempts for commit <hash>.
Switching to manual mode. Please resolve the conflicts manually.
```

Update state: `conflict_mode: "manual"` (globally, or per-commit).

### Special Conflict Cases

**Binary file conflict:**
- ALWAYS force manual mode
- Tell the user: "Binary file conflict in <file>. Cannot auto-resolve. Please resolve manually."

**Submodule change:**
- ALWAYS warn and force manual mode
- Tell the user: "Submodule change detected in <path>. Submodule conflicts require careful manual handling."

**Dependency chain break:**
When a commit depends on a previously skipped commit (detect via file overlap):
```bash
# Check if this commit modifies files that a skipped commit also modified
# Compare file lists between current commit and previously skipped commits
git show --name-only <current-hash>
git show --name-only <skipped-hash>
```

If overlap detected, warn proactively:
```
WARNING: Commit <hash> modifies files also changed by skipped commit <skipped-hash>.
This may cause issues. Proceed carefully or consider going back to include the skipped commit.
```

---

## Context Management

### Principles

- **Successful cherry-picks**: Output ONE line only:
  ```
  [3/10] abc1234 Add feature X -- completed
  ```
- **Conflicts**: Full detail output (unavoidable)
- **Reviews**: Summarized to verdict + key issues only

### Session Counter

After each commit (success, skip, or fail), increment `commits_processed_this_session`.

### 5-Commit Reminder

When `commits_processed_this_session` reaches a multiple of 5:
```
--- Context check: <N> commits processed this session ---
Consider running /compact to free up context.
Progress: <completed>/<total> (<percentage>%)
```

### High Context Warning

If context usage feels high (many conflicts resolved, lots of output):
```
--- Context usage is high ---
Your progress is saved in .git/cherry-pick-batch.json.
Recommend: start a new session and run /cherry-pick-next to resume.
```

### Cross-Session Resume

The state file in `.git/cherry-pick-batch.json` enables seamless resume:
1. New session starts
2. User runs `/cherry-pick-next` or `/cherry-pick-status`
3. State file is loaded, position is recovered
4. `commits_processed_this_session` resets to 0
5. Execution continues from where it left off

---

## State Update Patterns

### On cherry-pick success:
```bash
bash scripts/state-update.sh "
  .commits[<idx>].status = \"completed\" |
  .commits[<idx>].cherry_pick_hash = \"<new-hash>\" |
  .current_index = <idx> |
  .stats.completed += 1 |
  .commits_processed_this_session += 1
"
```

### On conflict:
```bash
bash scripts/state-update.sh "
  .commits[<idx>].status = \"conflict\" |
  .commits[<idx>].conflict_files = [\"file1\", \"file2\"] |
  .current_index = <idx>
"
```

### On skip:
```bash
bash scripts/state-update.sh "
  .commits[<idx>].status = \"skipped\" |
  .commits[<idx>].skipped_reason = \"<reason>\" |
  .stats.skipped += 1 |
  .commits_processed_this_session += 1
"
```

### On failure:
```bash
bash scripts/state-update.sh "
  .commits[<idx>].status = \"failed\" |
  .stats.failed += 1 |
  .commits_processed_this_session += 1
"
```
