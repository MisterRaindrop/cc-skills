# Cherry-Pick Plan Skill

## Auto-trigger

Trigger this skill when the user mentions any of:
- "cherry-pick these commits"
- "cherry pick"
- "backport"
- "batch merge"
- "port changes from"
- "pick commits from"
- "selective merge"
- "cherry-pick from branch"

## Behavior

When triggered, guide the user through planning a batch cherry-pick operation.

### Step 1: Gather Information

Ask the user (if not already provided):
1. **Source commits**: Which commits to cherry-pick? Accept:
   - A branch name or range (`feature/upstream`, `main..feature`)
   - Specific commit hashes
   - A file with hashes (`@commits.txt`)
2. **Target branch**: Where to apply them? Default to current branch.

### Step 2: Execute Plan Command

Once you have source and target, follow the `/cherry-pick-plan` command instructions exactly. The command file is at `plugins/batch-cherry-pick/commands/cherry-pick-plan.md`.

Key steps:
- Validate clean working tree
- Resolve all commit metadata
- Detect already-applied commits
- Enable `git rerere`
- Create state file at `.git/cherry-pick-batch.json`
- Show plan table to user

### Step 3: User Confirmation

Present the plan table and ask the user to:
- Confirm the commit list (they can add/remove/reorder)
- Choose conflict mode: `manual` (default) or `auto`
- Choose post-resolution mode: `wait-for-review` (default) or `auto-continue`

**Important:** Default to the safest options (manual + wait-for-review). Only use auto modes if the user explicitly requests them.

### Step 4: Save and Suggest Next Step

After confirmation, save the state file and tell the user:
> Plan saved! Run `/cherry-pick-start` to begin execution.

## Important Notes

- NEVER start cherry-picking without user confirmation of the plan
- The user has context about their codebase that you don't -- respect their decisions about which commits to include/exclude
- Always use `-x` flag when cherry-picking (for traceability)
- State file lives in `.git/` so it persists across sessions and isn't tracked by git
