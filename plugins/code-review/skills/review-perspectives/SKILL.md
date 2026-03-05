# Review Perspectives - Role Definitions & Checklists

This skill defines the 9 review roles across both teams, their review checklists, and the severity classification system.

## When This Skill is Used

This skill is referenced by the **review-engine** skill during review phases. It is NOT directly triggered by the user.

---

## Severity Classification

| Severity | Meaning | Blocks Merge? | Action Required |
|----------|---------|---------------|-----------------|
| critical | Bug, security vulnerability, data loss risk | YES | Must fix before merge |
| major | Design flaw, significant logic issue | YES | Must fix or justify |
| minor | Style, naming, minor improvement | NO | Recommended fix |
| nit | Trivial preference | NO | Optional |
| praise | Something done well | N/A | Acknowledge |

---

## Team Alpha (Claude Team)

### Leader (Synthesis Role)

The Leader does NOT review code directly. Instead, the Leader:
1. Orchestrates the review process across both teams
2. Merges and deduplicates findings from all reviewers
3. Resolves conflicts between team opinions
4. Assigns final severity levels
5. Drives challenge rounds until convergence
6. Produces the final report and verdict

**Decision matrix for verdicts:**
- **APPROVE**: No critical/major issues. Minor/nit issues only.
- **REQUEST_CHANGES**: Any critical or major issue found by either team.
- **NEEDS_DISCUSSION**: Teams disagree on severity of key issues, or confidence is low.

### Product Manager (Team Alpha)

**Focus**: User impact, business logic correctness, edge cases.

**Checklist:**
- [ ] Does the change match the stated intent (commit message, PR description)?
- [ ] Are business rules correctly implemented?
- [ ] Are user-facing edge cases handled (empty input, boundary values, concurrent access)?
- [ ] Could this change cause user-visible regressions?
- [ ] Are error messages user-friendly and actionable?
- [ ] Is backwards compatibility preserved where expected?
- [ ] Are there accessibility or i18n concerns?

**Common findings:**
- Missing null/empty checks on user input
- Business logic that doesn't match requirements
- Edge cases not covered (off-by-one, timezone issues, locale-specific behavior)

### Architect (Team Alpha)

**Focus**: System design, security, scalability, coupling.

**Checklist:**
- [ ] Does the change respect existing architecture patterns?
- [ ] Are new dependencies justified and appropriate?
- [ ] Is the coupling between modules acceptable?
- [ ] Are there security concerns (injection, XSS, CSRF, auth bypass, secrets exposure)?
- [ ] Does the change scale appropriately (N+1 queries, unbounded lists, missing pagination)?
- [ ] Are API contracts preserved (breaking changes flagged)?
- [ ] Is error propagation correct (errors not swallowed, proper error types)?
- [ ] Are transactions used correctly (atomicity, isolation level)?

**Common findings:**
- Circular dependencies introduced
- Missing input sanitization (SQL injection, command injection, path traversal)
- N+1 query patterns
- Breaking API changes without versioning

### Senior Coder A (Team Alpha)

**Focus**: Bugs, logic errors, resource leaks, SOLID principles.

**Checklist:**
- [ ] Are there logic errors (wrong operator, inverted condition, off-by-one)?
- [ ] Are resources properly managed (file handles, connections, locks, memory)?
- [ ] Is error handling correct (all error paths covered, no silent failures)?
- [ ] Are type conversions safe (overflow, truncation, null coercion)?
- [ ] Is concurrency handled correctly (race conditions, deadlocks, thread safety)?
- [ ] Does the code follow SOLID principles where appropriate?
- [ ] Are invariants maintained (preconditions, postconditions, class invariants)?

**Common findings:**
- Resource leaks (unclosed streams, missing finally/defer)
- Race conditions in concurrent code
- Integer overflow in arithmetic
- Null pointer dereferences

### Coder B (Team Alpha)

**Focus**: Readability, test quality, complexity, KISS principle.

**Checklist:**
- [ ] Is the code readable and self-documenting?
- [ ] Are naming conventions consistent with the codebase?
- [ ] Is complexity manageable (cyclomatic complexity, nesting depth)?
- [ ] Are tests meaningful (not just testing framework, not tautological)?
- [ ] Do tests cover the happy path AND error cases?
- [ ] Is there unnecessary duplication that should be extracted?
- [ ] Are magic numbers/strings extracted to constants?
- [ ] Is the code unnecessarily clever when simple would suffice?

**Common findings:**
- Deeply nested conditionals (> 3 levels)
- Tests that always pass (mocking too aggressively)
- Duplicated code blocks that should be shared
- Overly complex abstractions for simple operations

---

## Team Beta (Codex Team / Claude Fallback)

### Product Analyst (Team Beta)

**Focus**: Challenge assumptions, what-if scenarios.

**Checklist:**
- [ ] What assumptions does this code make about its inputs?
- [ ] What happens if upstream services fail or return unexpected data?
- [ ] Are there timing-dependent behaviors that could cause issues?
- [ ] What if this code runs in a different environment (OS, timezone, locale)?
- [ ] What if the data volume is 10x or 100x expected?
- [ ] Are there feature flag or configuration interactions that could cause issues?

**Common findings:**
- Implicit assumptions about execution environment
- Missing timeout/retry logic for external calls
- Data format assumptions (always UTF-8, always JSON, always sorted)

### Systems Engineer (Team Beta)

**Focus**: Deployment risk, monitoring, operations.

**Checklist:**
- [ ] Can this change be deployed with zero downtime?
- [ ] Is there a safe rollback path?
- [ ] Are there database migration risks (long locks, data transformation)?
- [ ] Is adequate logging added for debugging production issues?
- [ ] Are metrics/alerts needed for the new functionality?
- [ ] Are health checks updated if needed?
- [ ] Could this change cause memory/CPU spikes under load?

**Common findings:**
- Missing structured logging for new code paths
- Database migrations that lock tables for too long
- No circuit breaker for new external service calls
- Missing rate limiting on new endpoints

### Developer C (Team Beta, Senior)

**Focus**: Alternative approaches, performance, stdlib reuse.

**Checklist:**
- [ ] Is there a simpler approach to achieve the same result?
- [ ] Are standard library functions used where applicable (instead of reinventing)?
- [ ] Are there performance concerns (unnecessary copies, allocation in hot paths)?
- [ ] Is the algorithm choice appropriate for the data size?
- [ ] Could lazy evaluation or caching improve performance?
- [ ] Are there existing utilities in the codebase that could be reused?

**Common findings:**
- Custom implementations of stdlib functionality
- O(n^2) algorithms where O(n log n) exists
- Unnecessary object allocation in loops
- Missing caching for expensive repeated computations

### Developer D (Team Beta)

**Focus**: Test coverage, defensive programming, boundary values.

**Checklist:**
- [ ] Are boundary values tested (0, 1, MAX, empty, null)?
- [ ] Are error paths tested (exceptions, timeouts, permission denied)?
- [ ] Is input validation sufficient at system boundaries?
- [ ] Are there defensive checks against data corruption?
- [ ] Are assertions/contracts used for internal invariants?
- [ ] Is the test isolation adequate (no shared mutable state between tests)?

**Common findings:**
- Missing boundary value tests
- No tests for error/exception paths
- Tests with side effects that affect other tests
- Missing input validation on public API surfaces

---

## Output Language Detection

Detect the output language by inspecting code comments and naming conventions in the diff:

1. **Scan comments**: Look for `//`, `#`, `/* */`, `<!-- -->`, docstrings
2. **Detect language**:
   - If > 60% of comments contain CJK characters (Chinese/Japanese/Korean) -> output in Chinese
   - If comments are in English or mixed -> output in English
3. **Variable naming**: If variable/function names use pinyin patterns, consider Chinese output
4. **Override**: User can set `--lang zh|en` to force a language

The review report and all findings should be in the detected (or configured) language.
The skill/command files themselves are always written in English.

---

## Finding Format

Each finding should follow this structure:

```
[ISSUE-<ID>] [<severity>] <title>
Role: <role name>
Team: <Alpha|Beta>
Location: <file>:<line> (if applicable)
Description: <detailed description>
Suggestion: <recommended fix> (if applicable)
```

Example:
```
[ISSUE-001] [critical] SQL injection in user search
Role: Architect
Team: Alpha
Location: src/api/users.py:42
Description: User input is directly interpolated into SQL query without parameterization.
Suggestion: Use parameterized queries: cursor.execute("SELECT * FROM users WHERE name = %s", (name,))
```
