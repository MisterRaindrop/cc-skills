# /review

Main entry point for code review. Auto-detects what to review and runs the multi-agent review engine.

## Usage

```
/review [--depth quick|standard|deep] [--lang zh|en]
```

**Options:**
- `--depth`: Review depth (default: auto-detected based on change size)
  - `quick`: Team Alpha only, 3 roles, 1 round, no challenge
  - `standard`: Alpha + Beta, all roles, up to 3 rounds, challenge if needed
  - `deep`: Alpha + Beta, all roles, up to 5 rounds, always challenge, production checks
- `--lang`: Output language override (default: auto-detected from code comments)

## Instructions

You are executing the `/review` command. Follow these steps precisely:

### Step 1: Check for Existing Review State

```bash
bash plugins/code-review/scripts/review-state.sh exists
```

If a state file exists:
- Read it: `bash plugins/code-review/scripts/review-state.sh read '.current_phase'`
- If `current_phase` is NOT `"complete"`: ask user to resume or start fresh
- If `current_phase` is `"complete"`: ask user to view previous results or start fresh

If starting fresh, delete old state:
```bash
bash plugins/code-review/scripts/review-state.sh delete
```

### Step 2: Auto-Detect Review Target

Detect what to review, in order of priority:

```bash
# 1. Check for staged changes
STAGED=$(git diff --cached --stat)

# 2. Check for unstaged changes
UNSTAGED=$(git diff --stat)

# 3. Fall back to last commit
LAST_COMMIT=$(git log -1 --oneline)
```

Tell the user what will be reviewed:
```
Detected: <N> staged files / <N> unstaged changes / last commit <hash> <subject>
Reviewing: <target description>
```

### Step 3: Auto-Detect Depth

If `--depth` not specified:

```bash
# Count total changed lines
DIFF=$(bash plugins/code-review/scripts/collect-diff.sh staged 2>/dev/null || \
       bash plugins/code-review/scripts/collect-diff.sh unstaged 2>/dev/null || \
       bash plugins/code-review/scripts/collect-diff.sh commit HEAD 2>/dev/null)
LINE_COUNT=$(echo "$DIFF" | wc -l)
```

| Lines Changed | Default Depth |
|---------------|---------------|
| < 50 | quick |
| 50 - 500 | standard |
| > 500 | deep |

Show the user: `Depth: <depth> (auto-detected, <N> lines changed)`

### Step 4: Collect Diff

```bash
DIFF_OUTPUT=$(bash plugins/code-review/scripts/collect-diff.sh <mode> [args...])
```

If diff collection fails, report the error and stop.

### Step 5: Run Review Engine

Follow the **review-engine** skill protocol exactly. The skill is defined at `plugins/code-review/skills/review-engine/SKILL.md`.

Execute all 6 phases:
1. Preparation (context gathering, language detection, state init)
2. Team Alpha Review
3. Team Beta Review (if depth >= standard)
4. Leader Synthesis
5. Challenge Round (if applicable)
6. Final Report

### Step 6: Present Results

Display the final report from the review engine.

If verdict is `REQUEST_CHANGES`:
```
Next steps:
1. Fix the issues listed above
2. Run /review again to verify fixes
```

If verdict is `APPROVE`:
```
Code looks good! Safe to commit/merge.
```

If verdict is `NEEDS_DISCUSSION`:
```
Some issues need further discussion. Review the findings above and decide on next steps.
```
