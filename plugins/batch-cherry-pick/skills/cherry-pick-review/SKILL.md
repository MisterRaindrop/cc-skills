# Cherry-Pick Review Skill - Multi-Agent Review Coordination

This skill coordinates a multi-agent review of each cherry-picked commit. It uses a Leader + CoderA + CoderB (optional) architecture.

## Architecture

```
Leader (main session)
├── CoderA (Claude subagent via Agent tool)
└── CoderB (Codex CLI via Bash tool) -- optional, with fallback
```

- **CoderA**: Claude subagent spawned via the Agent tool
- **CoderB**: Codex CLI invoked via Bash. If unavailable, falls back to Claude-only review.
- **Leader**: Main session that synthesizes verdicts and makes final decision

## Review Flow

### Step 1: Prepare Review Materials

Gather the diff and context needed for review:

```bash
# Cherry-pick result diff
git diff HEAD~1..HEAD

# Original commit diff (for comparison)
git show <original-hash>

# Commit message
git log -1 --format="%B" HEAD

# Files changed
git diff --name-only HEAD~1..HEAD
```

### Step 2: Check Codex Availability

```bash
which codex 2>/dev/null
```

- **If Codex is found:** Use both CoderA and CoderB
- **If Codex is NOT found:** Warn the user:
  ```
  Note: Codex CLI not found. Falling back to Claude-only review (single reviewer).
  For dual-reviewer setup, install Codex CLI.
  ```
  Then use only CoderA (as a senior reviewer with higher scrutiny).

### Step 3: Dispatch Reviewers (in parallel)

**CoderA (Claude subagent)** -- Always dispatched:

Use the Agent tool with a prompt like:

```
You are CoderA, a code review expert. Review this cherry-pick for correctness.

ORIGINAL COMMIT (<original-hash>):
<original commit diff>

CHERRY-PICK RESULT:
<cherry-pick diff>

COMMIT MESSAGE:
<commit message>

Review criteria:
1. COMPLETENESS: Does the cherry-pick capture all changes from the original commit?
2. CONFLICT RESOLUTION: If there were conflicts, were they resolved correctly?
3. SYNTAX: No syntax errors, broken imports, or malformed code?
4. RUNTIME SAFETY: Could this change cause runtime errors, crashes, or data corruption?
5. MISSING CONTEXT: Are there dependencies on other commits that aren't present?

Respond in EXACTLY this format:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES:
- <issue 1, if any>
- <issue 2, if any>
(Write "none" if no issues)
```

**CoderB (Codex CLI)** -- Only if available:

```bash
codex --quiet --approval-mode full-auto \
  "Review this cherry-pick diff for correctness. Focus on runtime correctness, integration compatibility, and missing dependencies.

ORIGINAL COMMIT:
$(git show <original-hash> --stat)

CHERRY-PICK DIFF:
$(git diff HEAD~1..HEAD)

Respond with:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES: list any issues found, or 'none'"
```

**IMPORTANT:** Dispatch CoderA and CoderB IN PARALLEL (Agent + Bash simultaneously) to save time.

### Step 4: Parse Responses

Extract from each reviewer's response:
- `verdict`: APPROVE or REJECT
- `confidence`: HIGH, MEDIUM, or LOW
- `issues`: List of concerns (may be empty)

If a reviewer's response doesn't follow the format, attempt best-effort parsing. If unparseable, treat as `NEEDS_HUMAN_REVIEW`.

### Step 5: Leader Synthesis

**When both reviewers are available:**

| CoderA Verdict | CoderB Verdict | Leader Decision |
|----------------|----------------|-----------------|
| APPROVE (HIGH/MED) | APPROVE (HIGH/MED) | **APPROVED** |
| REJECT (any) | REJECT (any) | **REJECTED** |
| APPROVE | REJECT | Analyze: substantive issues -> REJECT; stylistic only -> APPROVE with notes |
| REJECT | APPROVE | Analyze: substantive issues -> REJECT; stylistic only -> APPROVE with notes |
| Either LOW confidence | Any | **NEEDS_HUMAN_REVIEW** |

**When only CoderA (Codex unavailable):**

| CoderA Verdict | Leader Decision |
|----------------|-----------------|
| APPROVE (HIGH) | **APPROVED** |
| APPROVE (MEDIUM) | **APPROVED** with notes shown to user |
| APPROVE (LOW) | **NEEDS_HUMAN_REVIEW** |
| REJECT (any) | **NEEDS_HUMAN_REVIEW** |

Note: With single reviewer, REJECT doesn't auto-reject -- it escalates to user since we have less confidence without a second opinion.

### Step 6: Act on Decision

**APPROVED:**
```
Review: APPROVED
CoderA: APPROVE (HIGH) | CoderB: APPROVE (HIGH)
```
Update commit status to `"completed"`.

**APPROVED with notes:**
```
Review: APPROVED (with notes)
CoderA: APPROVE (MEDIUM) | CoderB: APPROVE (HIGH)
Notes:
- <issue from reviewer>
```
Update commit status to `"completed"`. Show notes to user but don't block.

**REJECTED:**
```
Review: REJECTED
CoderA: REJECT (HIGH) | CoderB: REJECT (MEDIUM)
Issues:
- <issue 1>
- <issue 2>

Options:
1. Revert this cherry-pick: git revert HEAD
2. Fix the issues manually, then amend
3. Accept anyway and continue: /cherry-pick-next --force
```
Update commit status to `"failed"`. STOP and wait for user.

**NEEDS_HUMAN_REVIEW:**
```
Review: NEEDS HUMAN REVIEW
CoderA: <verdict> (<confidence>) | CoderB: <verdict> (<confidence>)
Concerns:
- <issue 1>
- <issue 2>

Please review the changes and decide:
1. Accept: /cherry-pick-next
2. Revert: git revert HEAD
3. Skip remaining reviews: /cherry-pick-next --force
```
Update commit status to `"reviewing"`. STOP and wait for user.

### Step 7: Update State

Record review details in the commit's `review_details` field:

```json
{
  "coder_a_verdict": "APPROVE:HIGH",
  "coder_b_verdict": "APPROVE:MEDIUM",
  "leader_decision": "APPROVED",
  "issues": ["minor: consider adding a null check"]
}
```

If Codex was unavailable, record:
```json
{
  "coder_a_verdict": "APPROVE:HIGH",
  "coder_b_verdict": "UNAVAILABLE",
  "leader_decision": "APPROVED",
  "issues": []
}
```

## Important Notes

- Reviews should be FAST. Don't over-analyze simple commits.
- For trivial changes (docs, comments, version bumps), CoderA alone with HIGH confidence is sufficient.
- The review is a safety net, not a gate. The user has final authority.
- Keep review output concise -- 3-5 lines max for approved commits.
- Full review details are recorded in the state file for later reference.
