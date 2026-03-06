# /cherry-pick:commit

Quick cherry-pick a single commit with interactive conflict handling, review, and commit confirmation.

## Usage

```
/cherry-pick:commit <hash>
```

## Instructions

You are executing the `/cherry-pick:commit` command. Follow these steps precisely:

### Step 1: Validate

```bash
# Ensure git repo
git rev-parse --git-dir

# Clean working tree
git status --porcelain

# No cherry-pick in progress
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"

# Resolve commit
git log -1 --format="%H %h %an %s" <hash>
```

If working tree is dirty, warn the user and stop.

### Step 2: Execute Cherry-Pick

Use `--no-commit` so the user has full control before committing:

```bash
# Regular commit
git cherry-pick --no-commit -x <hash>

# Merge commit (detect via parent count)
PARENTS=$(git cat-file -p <hash> | grep -c "^parent")
if [ "$PARENTS" -gt 1 ]; then
  git cherry-pick --no-commit -x -m 1 <hash>
fi
```

### Step 3: Handle Result

**Success (no conflict):**

Show a brief summary of staged changes:
```bash
git diff --cached --stat
```

Then go to Step 4.

**Conflict:**

Show conflicted files with context:
```bash
git diff --name-only --diff-filter=U
```

For each conflicted file, show the conflict regions (first few lines of markers):
```bash
grep -n '<<<<<<<\|=======\|>>>>>>>' <file> | head -10
```

Also show the original commit's intent:
```bash
git show <hash> --stat
```

Ask the user in natural language:

> Found conflicts in N files. Would you like me to auto-resolve them?

- **User says yes**: Invoke the **cherry-pick-engine** skill's conflict resolution protocol. For each conflicted file:
  1. Read the conflict markers
  2. Read the original commit diff to understand intent
  3. Read the file's current state on target branch
  4. Resolve intelligently, preferring the cherry-picked changes for clear updates
  5. Validate no conflict markers remain
  6. `git add <resolved-files>`

  If auto-resolution fails, tell the user and wait for manual resolution.

- **User says no**: Tell the user to resolve manually, then say "let me know when you're done" and wait. When the user indicates they're done, validate:
  ```bash
  # No unmerged files
  git diff --name-only --diff-filter=U
  # No conflict markers in staged files
  git diff --cached | grep -c '<<<<<<<'
  ```
  Then `git add -u` and continue.

### Step 4: Ask About Review

Show the staged changes summary:
```bash
git diff --cached --stat
```

Ask the user:

> Changes are staged. Would you like me to run a review? (/cherry-pick:review)

- **User says yes/review**: Execute the `/cherry-pick:review` command (see `commands/review.md`). After review completes, continue to Step 5.
- **User says no/skip**: Go directly to Step 5.

### Step 5: Ask About Commit

Show final diff stat:
```bash
git diff --cached --stat
```

Ask the user:

> Ready to commit. Proceed?

- **User says yes**: Commit with the original message plus cherry-pick trailer:
  ```bash
  ORIGINAL_MSG=$(git log -1 --format="%B" <hash>)
  git commit -m "$ORIGINAL_MSG" -m "(cherry picked from commit <hash>)"
  ```
  Then show: `Cherry-pick complete: <new_hash>`

- **User says no**: Leave changes staged. Tell the user they can commit manually or `git cherry-pick --abort` to undo.

### Important Notes

- ALWAYS use `-x` semantics (add cherry-pick trailer) for traceability
- Use `--no-commit` to give the user control
- Keep output concise — show stats, not full diffs
- Each question is a natural pause point; wait for the user's response before continuing
