# /cherry-pick:review

Multi-agent adversarial code review for the current cherry-pick. Uses dual-reviewer architecture for high-confidence verification.

## Usage

```
/cherry-pick:review
```

Can be invoked:
- Explicitly by the user at any time (when there are staged/committed cherry-pick changes)
- As part of the `/cherry-pick:commit`, `/cherry-pick:plan`, or `/cherry-pick:batch` flow when the user agrees to review

## Instructions

You are executing the `/cherry-pick:review` command. Follow these steps precisely:

### Step 1: Detect Context

Determine what to review:

```bash
# Check if there's a cherry-pick in progress (staged but not committed)
STAGED=$(git diff --cached --stat)

# Check the most recent commit (if already committed)
LAST_COMMIT=$(git log -1 --format="%H %s")

# Check if we're in a batch (state file exists)
STATE_FILE="$(git rev-parse --git-dir)/cherry-pick-batch.json"
```

**If staged changes exist** (from `--no-commit` flow): Review the staged diff.
**If no staged changes**: Review the last commit (assume it's the cherry-pick result).
**If nothing to review**: Tell the user and stop.

### Step 2: Gather Review Materials

```bash
# The cherry-pick diff (staged or committed)
# Staged:
git diff --cached
# Or committed:
git diff HEAD~1..HEAD

# Files changed
git diff --cached --name-only  # or HEAD~1..HEAD --name-only

# Try to find the original commit hash from cherry-pick context
# Look for it in batch state, or in commit message trailer
```

If the original commit hash is available:
```bash
# Original commit diff for comparison
git show <original-hash>
```

### Step 3: Check Codex Availability

```bash
which codex 2>/dev/null
```

- **Codex found**: Use dual-reviewer mode (CoderA + CoderB)
- **Codex not found**: Use single-reviewer mode (CoderA with heightened scrutiny). Note this to the user:
  > Note: Codex CLI not found. Running single-reviewer mode.

### Step 4: Dispatch Reviewers

**CoderA (Claude subagent)** — Always dispatched via the Agent tool:

Prompt:
```
You are CoderA, a senior code reviewer. Review this cherry-pick for correctness.

CHERRY-PICK DIFF:
<diff content>

ORIGINAL COMMIT (if available):
<original diff>

FILES CHANGED:
<file list>

Review criteria:
1. COMPLETENESS: Does the cherry-pick capture all intended changes?
2. CONFLICT RESOLUTION: If conflicts were resolved, is the resolution correct?
3. SYNTAX: No syntax errors, broken imports, or malformed code?
4. RUNTIME SAFETY: Could this cause runtime errors, crashes, or data corruption?
5. MISSING CONTEXT: Are there dependencies not present on the target branch?

Respond in EXACTLY this format:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES:
- <issue 1, if any>
- <issue 2, if any>
(Write "none" if no issues)
```

**CoderB (Codex CLI)** — Only if available, dispatched IN PARALLEL with CoderA:

```bash
codex --quiet --approval-mode full-auto \
  "Review this cherry-pick diff for correctness. Focus on runtime safety, integration compatibility, and missing dependencies.

CHERRY-PICK DIFF:
$(git diff --cached)  # or HEAD~1..HEAD

Respond with:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES: list any issues, or 'none'"
```

### Step 5: Synthesize Verdicts

**Dual-reviewer mode:**

| CoderA | CoderB | Decision |
|--------|--------|----------|
| APPROVE (HIGH/MED) | APPROVE (HIGH/MED) | APPROVED |
| REJECT (any) | REJECT (any) | REJECTED |
| APPROVE | REJECT | Analyze issues — substantive → REJECTED; stylistic → APPROVED with notes |
| REJECT | APPROVE | Analyze issues — substantive → REJECTED; stylistic → APPROVED with notes |
| Either LOW confidence | Any | NEEDS_HUMAN_REVIEW |

**Single-reviewer mode (no Codex):**

| CoderA | Decision |
|--------|----------|
| APPROVE (HIGH) | APPROVED |
| APPROVE (MEDIUM) | APPROVED with notes |
| APPROVE (LOW) | NEEDS_HUMAN_REVIEW |
| REJECT (any) | NEEDS_HUMAN_REVIEW (escalate, since single opinion) |

### Step 6: Present Results

**APPROVED:**
```
Review: APPROVED
CoderA: APPROVE (HIGH) | CoderB: APPROVE (HIGH)
No issues found.
```

**APPROVED with notes:**
```
Review: APPROVED (with notes)
CoderA: APPROVE (MEDIUM) | CoderB: APPROVE (HIGH)
Notes:
- <note from reviewer>
```

**REJECTED:**
```
Review: REJECTED
CoderA: REJECT (HIGH) | CoderB: REJECT (MEDIUM)
Issues:
- <issue 1>
- <issue 2>

The cherry-pick has issues. You can:
- Fix the issues and re-run /cherry-pick:review
- Accept anyway and proceed with commit
- Abort with `git checkout -- .` (discard staged) or `git revert HEAD` (if committed)
```

**NEEDS_HUMAN_REVIEW:**
```
Review: NEEDS HUMAN REVIEW
CoderA: <verdict> (<confidence>) | CoderB: <verdict> (<confidence>)
Concerns:
- <concern 1>

Please review and decide whether to proceed.
```

### Step 7: Update Batch State (if applicable)

If running within a batch (`cherry-pick-batch.json` exists), update the current commit's `review_details`:

```json
{
  "coder_a_verdict": "APPROVE:HIGH",
  "coder_b_verdict": "APPROVE:MEDIUM",
  "leader_decision": "APPROVED",
  "issues": []
}
```

### Important Notes

- Dispatch CoderA and CoderB IN PARALLEL to save time
- Reviews should be FAST — don't over-analyze trivial changes
- For trivial changes (docs, comments, version bumps), a quick single-reviewer APPROVE is fine
- The review is a safety net, not a gate — the user has final authority
- Keep output concise: 3-5 lines for approved, more detail for rejected
