# Cherry-Pick Review Skill

Multi-agent adversarial code review for cherry-pick results. Uses Leader + CoderA + CoderB (optional) architecture.

## Auto-trigger

Do NOT auto-trigger this skill. It is invoked explicitly via `/cherry-pick:review` or when the user agrees to review during the cherry-pick flow.

## Architecture

```
Leader (main session)
├── CoderA (Claude subagent via Agent tool)
└── CoderB (Codex CLI via Bash tool) — optional
```

- **CoderA**: Claude subagent, always available
- **CoderB**: Codex CLI, optional (falls back to single-reviewer mode)
- **Leader**: Main session, synthesizes verdicts

## Review Protocol

### Step 1: Gather Materials

```bash
# Detect: staged changes or last commit
STAGED=$(git diff --cached --stat)

if [ -n "$STAGED" ]; then
  # Review staged changes
  DIFF=$(git diff --cached)
  FILES=$(git diff --cached --name-only)
else
  # Review last commit
  DIFF=$(git diff HEAD~1..HEAD)
  FILES=$(git diff --name-only HEAD~1..HEAD)
fi
```

If original commit hash is known (from batch state or context):
```bash
ORIGINAL_DIFF=$(git show <original-hash>)
```

### Step 2: Dispatch Reviewers (in parallel)

**CoderA** — Always dispatched via Agent tool:

```
You are CoderA, a senior code reviewer. Review this cherry-pick for correctness.

CHERRY-PICK DIFF:
<diff>

ORIGINAL COMMIT (if available):
<original diff>

Review criteria:
1. COMPLETENESS: All intended changes captured?
2. CONFLICT RESOLUTION: Correctly resolved?
3. SYNTAX: No errors, broken imports, malformed code?
4. RUNTIME SAFETY: Could cause crashes or data corruption?
5. MISSING CONTEXT: Dependencies not on target branch?

Respond EXACTLY:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES:
- <issue, if any>
(Write "none" if no issues)
```

**CoderB** — Only if `which codex` succeeds, dispatched IN PARALLEL with CoderA:

```bash
codex --quiet --approval-mode full-auto \
  "Review this cherry-pick diff. Focus on runtime safety and missing dependencies.

DIFF:
$(git diff --cached || git diff HEAD~1..HEAD)

Respond:
VERDICT: APPROVE or REJECT
CONFIDENCE: HIGH, MEDIUM, or LOW
ISSUES: list issues or 'none'"
```

### Step 3: Synthesize

**Dual-reviewer:**

| CoderA | CoderB | Decision |
|--------|--------|----------|
| APPROVE (HIGH/MED) | APPROVE (HIGH/MED) | APPROVED |
| REJECT | REJECT | REJECTED |
| Disagree | — | Analyze: substantive issues → REJECTED; stylistic → APPROVED with notes |
| LOW confidence | Any | NEEDS_HUMAN_REVIEW |

**Single-reviewer (no Codex):**

| CoderA | Decision |
|--------|----------|
| APPROVE (HIGH) | APPROVED |
| APPROVE (MED) | APPROVED with notes |
| APPROVE (LOW) | NEEDS_HUMAN_REVIEW |
| REJECT | NEEDS_HUMAN_REVIEW |

### Step 4: Output

Keep it concise:

- **APPROVED**: 2-3 lines
- **APPROVED with notes**: 3-5 lines
- **REJECTED**: Full detail + user options
- **NEEDS_HUMAN_REVIEW**: Concerns + ask user to decide

### Step 5: State Update (batch mode)

If `cherry-pick-batch.json` exists, record:

```json
{
  "coder_a_verdict": "APPROVE:HIGH",
  "coder_b_verdict": "APPROVE:MEDIUM",
  "leader_decision": "APPROVED",
  "issues": []
}
```

## Important Notes

- Dispatch CoderA and CoderB IN PARALLEL
- Trivial changes (docs, comments) → quick single-reviewer approval is fine
- Review is a safety net, not a gate — user has final authority
- 3-5 lines max for approved commits
