# Cherry-Pick Engine Skill

Core execution engine for all cherry-pick operations. Handles cherry-pick execution, conflict resolution, state management, and context management.

## Auto-trigger

Trigger this skill when the user mentions any of:
- "cherry-pick this commit"
- "cherry pick"
- "backport"
- "port changes from"
- "pick commit"
- "selective merge"
- "cherry-pick from branch"

When triggered, determine the appropriate command:
- Single commit hash → suggest `/cherry-pick:commit <hash>` or `/cherry-pick:plan <hash>`
- Multiple commits or branch range → suggest `/cherry-pick:batch <source>`

## Cherry-Pick Execution Protocol

This protocol is shared by `/cherry-pick:commit`, `/cherry-pick:plan`, and `/cherry-pick:batch`.

### Pre-flight Checks

Before each cherry-pick:

```bash
# Clean working tree
test -z "$(git status --porcelain)"

# No cherry-pick in progress
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"

# Commit exists
git cat-file -t <hash>
```

### Execute Cherry-Pick

**CRITICAL: Always use `--no-commit -x` for full user control and traceability.**

```bash
# Regular commit
git cherry-pick --no-commit -x <hash>

# Merge commit (parent count > 1)
git cherry-pick --no-commit -x -m 1 <hash>
```

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | Success | Show staged changes summary |
| 1 | Conflict | Enter conflict handling |
| 128 | Fatal error | Report to user, stop |

**Empty cherry-pick:** If git reports nothing to commit, ask user to skip or `--allow-empty`.

---

## Conflict Resolution

### Identify Conflicts

```bash
git diff --name-only --diff-filter=U
```

For each conflicted file, show conflict regions:
```bash
grep -n '<<<<<<<\|=======\|>>>>>>>' <file> | head -10
```

### Auto-Resolution (when user agrees or --auto mode)

For each conflicted file:

1. **Read** the conflict markers in the file
2. **Read** the original commit's diff (`git show <hash> -- <file>`) to understand intent
3. **Read** the target branch's version (`git show HEAD:<file>`) for context
4. **Resolve** intelligently:
   - Additive changes (new functions, imports): keep both sides
   - Modification conflicts: prefer cherry-picked version for clear updates
   - Deletion conflicts: flag for user review
5. **Write** the resolved file
6. **Validate**: ensure no conflict markers remain
7. **Stage**: `git add <file>`

After resolving all files:
```bash
# Final validation
git diff --name-only --diff-filter=U  # Should be empty
git diff --cached | grep -c '<<<<<<<'  # Should be 0
```

If validation fails, inform the user and wait for manual intervention.

### Special Cases

**Binary files**: Always require manual resolution. Tell the user.
**Submodules**: Always require manual resolution. Warn the user.

---

## Commit Protocol

When the user confirms commit:

```bash
# Get original commit message
ORIGINAL_MSG=$(git log -1 --format="%B" <original-hash>)

# Commit with cherry-pick trailer
git commit -m "$ORIGINAL_MSG

(cherry picked from commit <original-hash>)"
```

---

## Batch State Management

### State File

Location: `.git/cherry-pick-batch.json`

Only used by `/cherry-pick:batch`. Single-commit commands (`/cherry-pick:commit`, `/cherry-pick:plan`) do NOT create state files.

### Reading State

```bash
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
cat "$STATE_FILE" | jq '<query>'
```

### Updating State

After each commit in batch mode, update:
- `commits[idx].status` → "completed" / "skipped" / "failed"
- `commits[idx].cherry_pick_hash` → new commit hash
- `stats` counters
- `commits_processed_this_session` += 1
- `updated_at` → current timestamp

### Cross-Session Resume

The state file enables resume across sessions:
1. User starts a new session
2. Runs `/cherry-pick:batch` (any source)
3. Detects existing state file → asks to resume
4. `commits_processed_this_session` resets to 0
5. Continues from the first "pending" commit

---

## Context Management (Batch Mode)

### Principles

- **Successful picks**: One-line output: `[3/10] abc1234 Add feature X — completed`
- **Conflicts**: Full detail (unavoidable)
- **Reviews**: Summarized to verdict only

### 5-Commit Reminder

Every 5 commits processed in a session:
```
--- Processed N commits this session. Consider /compact to free context. ---
Progress: completed/total
```

### High Context Warning

When many conflicts or verbose output has accumulated:
```
--- Context may be getting large. Progress is saved — you can start a new session and resume. ---
```
