# /cherry-pick:plan

Carefully analyze a commit before cherry-picking. Read the code, assess risks, present a merge plan, and execute only after user confirmation.

## Usage

```
/cherry-pick:plan <hash>
```

## Instructions

You are executing the `/cherry-pick:plan` command. Follow these steps precisely:

### Step 1: Validate

```bash
git rev-parse --git-dir
git status --porcelain
test ! -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD"
git log -1 --format="%H %h %an <%ae> %s" <hash>
```

If working tree is dirty, warn and stop.

### Step 2: Deep Analysis

Gather comprehensive information about the commit:

```bash
# Full commit metadata
git log -1 --format="%H%n%an <%ae>%n%ai%n%B" <hash>

# Files changed with stats
git show <hash> --stat

# Full diff
git show <hash>

# Check if already applied
git log --grep="cherry picked from commit <hash>" --oneline
```

Read and understand:
1. **What the commit does** — summarize the changes in plain language
2. **Which files are modified** — list each file and what changed in it
3. **Dependencies** — does this commit depend on other commits not present on the target branch?

### Step 3: Assess Target Branch

For each file modified by the commit, check the current state on the target branch:

```bash
# Current branch (target)
git branch --show-current

# For each modified file, check if it exists and its current state
git show HEAD:<file> 2>/dev/null

# Try a dry-run merge to predict conflicts
git cherry-pick --no-commit -x <hash> 2>&1
git diff --name-only --diff-filter=U  # Check for conflicts
git cherry-pick --abort 2>/dev/null   # Clean up dry run
```

### Step 4: Present the Plan

Output a structured analysis:

```
## Cherry-Pick Plan

**Commit**: <short_hash> — <subject>
**Author**: <author>
**Date**: <date>

### What This Commit Does
<2-3 sentence summary of the commit's purpose and changes>

### Files Modified (<N> files)
| File | Change Type | Risk |
|------|-------------|------|
| src/foo.ts | New function `bar()` added | Low — no conflict expected |
| src/utils.ts | Modified lines 42-58 | High — diverged on target branch |
| tests/foo.test.ts | New test cases | Low — additive change |

### Potential Risks
- <risk 1: e.g., "src/utils.ts has diverged significantly on target branch, lines 42-58 will conflict">
- <risk 2: e.g., "This commit references `helperX()` which was introduced in commit def5678, not present on target">
- Or: "No significant risks detected."

### Merge Strategy
1. <step-by-step description of how the merge will proceed>
2. <e.g., "src/foo.ts — direct apply, no conflicts expected">
3. <e.g., "src/utils.ts — will need manual adaptation at line 45 where API signature changed">

Proceed with cherry-pick? (Y/n)
```

### Step 5: Wait for User Confirmation

**STOP and wait.** Do NOT proceed until the user explicitly confirms.

The user may:
- Confirm → proceed to Step 6
- Ask questions → answer them, then re-ask for confirmation
- Reject → stop, do nothing

### Step 6: Execute

Once confirmed, follow the same execution flow as `/cherry-pick:commit`:

1. `git cherry-pick --no-commit -x <hash>` (or `-m 1` for merge commits)
2. Handle conflicts (ask user: auto-resolve or manual?)
3. Ask about review
4. Ask about commit

The only difference from `/cherry-pick:commit` is that the user has already seen the full analysis, so keep the execution output concise.

### Important Notes

- The dry-run in Step 3 MUST be fully cleaned up (`git cherry-pick --abort`) before presenting the plan
- Be honest about risks — don't downplay potential issues
- If the commit is trivial (docs, comments, version bump), keep the plan brief
- If the commit is complex, be thorough in the analysis
