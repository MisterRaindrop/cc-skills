# Review Engine - Multi-Round Dual-Team Orchestration

This is the core orchestration engine for the multi-agent adversarial code review. It coordinates Team Alpha (Claude), Team Beta (Codex/Claude fallback), and the Leader synthesis process.

## When This Skill is Used

This skill is invoked by commands (`/review`, `/review-commit`, `/review-branch`) and by the `code-review-trigger` skill. It is NOT directly triggered by the user.

## Scripts and Templates

- **Diff collection**: `plugins/code-review/scripts/collect-diff.sh`
- **Codex detection**: `plugins/code-review/scripts/detect-codex.sh`
- **Codex invocation**: `plugins/code-review/scripts/run-codex-review.sh`
- **State management**: `plugins/code-review/scripts/review-state.sh`
- **Codex prompt template**: `plugins/code-review/templates/codex-prompt.md`
- **Role definitions**: `plugins/code-review/skills/review-perspectives/SKILL.md`

## State File

Location: `.git/code-review-state.json` (not tracked by git)

```json
{
  "version": 1,
  "created_at": "<ISO-timestamp>",
  "updated_at": "<ISO-timestamp>",
  "target": {
    "mode": "staged|commit|branch",
    "commits": ["<hash>"],
    "branch": "<branch-name>",
    "diff_stats": { "files": 0, "additions": 0, "deletions": 0 }
  },
  "config": {
    "depth": "quick|standard|deep",
    "lang": "auto|zh|en",
    "codex_available": false,
    "max_rounds": 3
  },
  "current_phase": "preparation|alpha_review|beta_review|synthesis|challenge|complete",
  "rounds": [],
  "all_issues": [],
  "praise_items": [],
  "verdict": null
}
```

---

## Review Flow

### Phase 1: Preparation

**Step 1.1: Collect diff and context**

```bash
# Collect the diff based on mode
bash plugins/code-review/scripts/collect-diff.sh <mode> [args...]
```

Capture both stdout (diff content) and stderr (metadata).

**Step 1.2: Gather repository context**

```bash
# Detect primary language
git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -5

# Check for linter config
ls -la .eslintrc* .prettierrc* .pylintrc pyproject.toml .rubocop.yml .golangci.yml 2>/dev/null || true

# Check for test framework
ls -la jest.config* pytest.ini vitest.config* .rspec 2>/dev/null || true
```

**Step 1.3: Detect output language**

Inspect comments in the diff:
1. Extract comment lines (lines starting with `//`, `#`, `/*`, `*`, `<!--`, or within docstrings)
2. Count CJK characters vs ASCII characters in comments
3. If > 60% CJK characters -> use Chinese for output
4. Otherwise -> use English
5. Respect `--lang` override if provided

**Step 1.4: Check Codex CLI availability**

```bash
bash plugins/code-review/scripts/detect-codex.sh
```

If exit code is 1 (not found):
```
Note: Codex CLI not found. Team Beta will be simulated by Claude independently.
For dual-engine review, install: npm i -g @openai/codex
```

**Step 1.5: Initialize state file**

```bash
bash plugins/code-review/scripts/review-state.sh write '<initial-state-json>'
```

Update `current_phase` to `"alpha_review"`.

---

### Phase 2: Team Alpha Review (Claude)

The main Claude session acts as Team Alpha. Review the diff from each role's perspective sequentially.

**Depth controls which roles are active:**

| Depth | Active Alpha Roles |
|-------|-------------------|
| quick | Product Manager, Coder A, Coder B |
| standard | Product Manager, Architect, Coder A, Coder B |
| deep | Product Manager, Architect, Coder A, Coder B (all) |

**For each active role:**

1. Read the role's checklist from the review-perspectives skill
2. Analyze the diff against the checklist
3. Report findings using the standard format:
   ```
   [ISSUE-<ID>] [<severity>] <title>
   Role: <role>
   Team: Alpha
   Location: <file>:<line>
   Description: <details>
   Suggestion: <fix>
   ```
4. Also note any praise items

**Output format for Alpha review:**

```
## Team Alpha Review

### Product Manager
- [ISSUE-001] [minor] Missing input validation for empty username
  Location: src/api/auth.py:35
  ...

### Architect
- [ISSUE-002] [critical] SQL injection in search endpoint
  Location: src/api/search.py:42
  ...

### Senior Coder A
- (no issues found)

### Coder B
- [praise] Clean separation of concerns in the new service layer
  ...
```

Update state: add all findings to `all_issues[]`, update `current_phase` to `"beta_review"`.

---

### Phase 3: Team Beta Review (Codex CLI / Claude Fallback)

**If Codex CLI is available:**

1. Read the template from `plugins/code-review/templates/codex-prompt.md`
2. Replace `{{DIFF_CONTENT}}` with the actual diff
3. Write the prompt to a temporary file
4. Invoke Codex:
   ```bash
   bash plugins/code-review/scripts/run-codex-review.sh <mode> [args...] <prompt-file>
   ```
5. Parse the Codex output for findings

**If Codex CLI is NOT available (Claude fallback):**

Claude simulates Team Beta independently. **CRITICAL**: To avoid anchoring bias, Team Beta must review the diff WITHOUT seeing Team Alpha's findings. The approach:

1. Use the Agent tool to spawn a subagent with the Team Beta prompt
2. The subagent receives ONLY the diff and the Team Beta role definitions
3. The subagent returns its independent findings

**Agent prompt for Team Beta fallback:**

```
You are Team Beta, an independent code review team. You have NOT seen any other review.
Review the following code changes from these 4 perspectives:

1. Product Analyst: Challenge assumptions, what-if scenarios
2. Systems Engineer: Deployment risk, monitoring, operations
3. Developer C (Senior): Alternative approaches, performance, stdlib reuse
4. Developer D: Test coverage, defensive programming, boundary values

[Include role checklists from review-perspectives skill]

DIFF:
<diff content>

For each finding, use this format:
[severity] <title> (file:line)
Description: <details>
Suggestion: <fix>

Classify severity as: critical, major, minor, nit, praise

End with:
VERDICT: APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION
CRITICAL_COUNT: <N>
MAJOR_COUNT: <N>
```

**Depth controls which Beta roles are active:**

| Depth | Active Beta Roles |
|-------|------------------|
| quick | (no Beta review) |
| standard | Product Analyst, Systems Engineer, Developer C, Developer D |
| deep | Product Analyst, Systems Engineer, Developer C, Developer D |

**If depth is `quick`**: Skip Phase 3 entirely, go to Phase 4.

Update state: add Beta findings to `all_issues[]`, update `current_phase` to `"synthesis"`.

---

### Phase 4: Leader Synthesis (Claude)

The Leader (main session) merges findings from both teams.

**Step 4.1: Deduplicate findings**

Compare all issues from Alpha and Beta:
- If two issues reference the same file:line and same type of problem -> merge into one, note both teams found it
- If issues are similar but not identical -> keep both but link them
- Assign sequential ISSUE IDs to deduplicated list

**Step 4.2: Resolve severity conflicts**

If Alpha and Beta disagree on severity for the same issue:
- Take the HIGHER severity (err on the side of caution)
- Note the disagreement in the issue record

**Step 4.3: Identify challenge-round candidates**

Issues that need challenge-round discussion:
- Severity disagreements between teams
- Issues where one team says "critical" and the other didn't find it
- Conflicting recommendations (Alpha says do X, Beta says do Y)

**Step 4.4: Assign final issue IDs and sort**

Sort all issues by severity (critical > major > minor > nit), then by file location.

Update state: finalize `all_issues[]`, update `current_phase` to `"challenge"` if needed, or `"complete"`.

---

### Phase 5: Challenge Round (Conditional, Multi-Round)

**When to run:**
- `deep` depth: ALWAYS run at least one challenge round
- `standard` depth: Only if there are severity disagreements or conflicting recommendations
- `quick` depth: NEVER run

**Challenge round process:**

For each disputed item:

1. Present both teams' positions:
   ```
   ISSUE-005: [Alpha: major] [Beta: critical] Unbounded query in user list endpoint
   Alpha position: Major because pagination exists but isn't enforced
   Beta position: Critical because admin endpoint has no pagination at all
   ```

2. The Leader evaluates:
   - Which team's reasoning is more convincing?
   - Is additional context needed?
   - What is the final severity?

3. Record the decision and reasoning

**Convergence criteria:**
- All disputed items have been resolved
- OR `max_rounds` reached (quick=1, standard=3, deep=5)

Update state: record challenge round results in `rounds[]`, update `current_phase` to `"complete"`.

---

### Phase 6: Final Report

Generate the final review report in the detected output language.

**Report structure:**

```
# Code Review Report

## Summary
- Target: <description of what was reviewed>
- Depth: <quick|standard|deep>
- Teams: <Alpha only | Alpha + Beta (Codex) | Alpha + Beta (Claude fallback)>
- Rounds: <N>

## Verdict: <APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION>

## Issues (<total count>)

### Critical (<count>)
| ID | Title | Location | Found By | Description |
|----|-------|----------|----------|-------------|
| ISSUE-001 | ... | file:line | Alpha:Architect | ... |

### Major (<count>)
| ID | Title | Location | Found By | Description |
|----|-------|----------|----------|-------------|
| ... |

### Minor (<count>)
...

### Nit (<count>)
...

## Praise
- <praise item 1>
- <praise item 2>

## Production Readiness (deep mode only)
- [ ] Error handling coverage
- [ ] Logging adequacy
- [ ] Performance under load
- [ ] Rollback safety
- [ ] Monitoring/alerting
- [ ] Documentation updated
```

**Verdict rules:**
- **APPROVE**: No critical or major issues
- **REQUEST_CHANGES**: Any critical or major issues found
- **NEEDS_DISCUSSION**: Teams could not converge, or confidence is low

Update state: set `verdict`, update `current_phase` to `"complete"`.

---

## Resume Support

If the state file exists and `current_phase` is not `"complete"`:
1. Load the state file
2. Report current phase and progress
3. Resume from the interrupted phase

If the state file exists and `current_phase` is `"complete"`:
1. Show the cached final report
2. Ask if the user wants to start a new review

---

## Context Management

- Keep Alpha review output concise: findings only, no verbose explanation
- Beta review (Codex/Agent): offloaded to separate process, results summarized
- Challenge rounds: only show disputed items, not full re-review
- Final report: structured table format for scannability
- If context is running high, suggest `/compact` before continuing
