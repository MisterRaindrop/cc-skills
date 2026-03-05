# Code Review Trigger Skill

## Auto-trigger

Trigger this skill when the user mentions any of:
- "review my code"
- "code review"
- "review these changes"
- "review this PR"
- "review this commit"
- "review this branch"
- "check my code"
- "audit this code"
- "look at my changes"

Chinese triggers:
- "代码审查"
- "审查代码"
- "看看我的代码"
- "检查代码"
- "代码检视"
- "review 一下"

## Behavior

When triggered, determine the most appropriate review mode and invoke the review engine.

### Step 1: Detect Review Target

Check what the user wants to review:

1. **If user mentions a commit hash or "commit"** -> Use `/review-commit` mode
2. **If user mentions a branch name or "branch"** -> Use `/review-branch` mode
3. **If user mentions "staged" or "changes"** -> Use `/review` (auto-detect) mode
4. **Otherwise** -> Auto-detect:
   ```bash
   # Check for staged changes first
   STAGED=$(git diff --cached --stat)
   if [ -n "$STAGED" ]; then
       # Review staged changes
   fi

   # Check for unstaged changes
   UNSTAGED=$(git diff --stat)
   if [ -n "$UNSTAGED" ]; then
       # Review unstaged changes
   fi

   # Fall back to last commit
   # Review HEAD commit
   ```

### Step 2: Determine Depth

If the user specifies depth, use it. Otherwise:
- Small changes (< 50 lines): default to `quick`
- Medium changes (50-500 lines): default to `standard`
- Large changes (> 500 lines): default to `deep`

The user can override with `--depth quick|standard|deep`.

### Step 3: Invoke Review Engine

Follow the **review-engine** skill protocol with the detected target and depth.

The review engine skill is at `plugins/code-review/skills/review-engine/SKILL.md`.

### Step 4: Handle Resume

If a review state file already exists (`.git/code-review-state.json`), ask the user:
> A previous review is in progress. Options:
> 1. Resume the previous review
> 2. Start a new review (discards previous state)

## Important Notes

- Default to the safest (most thorough) review when in doubt
- Always confirm the review target with the user before starting
- The trigger skill is a routing layer -- the actual review logic is in review-engine
