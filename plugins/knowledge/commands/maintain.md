# /knowledge:maintain

Scan the Obsidian knowledge base, identify expired content, backlogged notes, and orphaned plans, then execute archival or cleanup operations.

## Usage

```
/knowledge:maintain
```

## Prerequisites

- Obsidian must be running with MCP connection active
- `Knowledge/` directory structure must exist in the vault

## Instructions

You are executing the `/knowledge:maintain` command. Follow these steps precisely:

### Step 1: Get Today's Date

```bash
date +%Y-%m-%d
```

Record as `TODAY`.

### Step 2: Scan All Vault Files

Use `mcp__obsidian__list_vault_files` to recursively list all `.md` files in:
- `Knowledge/Projects/`
- `Knowledge/_inbox/`

Skip meta files: `_index.md`, `_taxonomy.md`, `_export.md`, `README.md`.

### Step 3: Read Each File's Frontmatter

For each non-meta file, use `mcp__obsidian__get_vault_file` (format: json) to extract:
- `title`, `date`, `status`, `content_type`, `review_after`

### Step 4: Classify and Generate Audit Report

**Category A — Expiration Candidates** (need review)
Condition: `status == "active"` AND `review_after < TODAY`

**Category B — Inbox Backlog**
Condition: file path contains `Knowledge/_inbox/`

**Category C — Missing Lifecycle Fields** (old-format notes)
Condition: `content_type` or `review_after` field missing, AND `status == "active"`

Present the report as a table:

```
## Knowledge Base Audit Report

### A. Expiration Candidates (N notes)
| File | content_type | review_after | Days overdue |
|------|-------------|--------------|--------------|
| ... | session | 2026-02-01 | 33 |

### B. Inbox Backlog (N items)
| File | Date | Title |
|------|------|-------|
| ... | 2026-02-15 | Draft: FDW concepts |

### C. Missing Lifecycle Fields (N notes)
| File | Missing Fields |
|------|---------------|
| ... | content_type, review_after |
```

Then process each category interactively.

### Step 5: Scan Orphaned Plans

Check `~/.claude/plans/` for plan files not yet archived to the vault:

```bash
ls ~/.claude/plans/ 2>/dev/null
```

For each plan file, check if a corresponding note exists in the vault.

### Step 6: Execute Operations Interactively

For each item, ask the user to choose:

**Category A (Expiration Candidates):**
- `[archive]` -> Set `status: archived` via `mcp__obsidian__patch_vault_file`
- `[outdated]` -> Set `status: outdated`
- `[keep]` -> Extend `review_after` by 30 days from today
- `[delete]` -> Requires double confirmation, then `mcp__obsidian__delete_vault_file`

**Category B (Inbox Backlog):**
- `[classify]` -> Analyze content, move to correct `Knowledge/Projects/{project}/` location
- `[delete]` -> Requires double confirmation

**Category C (Missing Lifecycle Fields):**
- `[add-lifecycle]` -> Infer `content_type` from content, calculate `review_after`, update frontmatter
- `[skip]` -> Skip this note

**Category D (Orphaned Plans):**
- `[archive]` -> Archive plan content to vault under the appropriate project
- `[skip]` -> Skip

### Step 7: Output Operation Summary

```
## Maintenance Complete

- Archived: N notes
- Marked outdated: N notes
- Extended review: N notes
- Deleted: N notes (with confirmation)
- Classified from inbox: N notes
- Lifecycle fields added: N notes
- Plans archived: N plans
```

## Important Notes

- **Delete is irreversible** — always require double confirmation
- **Archive != Delete**: `status: archived` means no longer active, but content is preserved
- **Plan originals are preserved** in `~/.claude/plans/` — never delete the source
- Process items in batches if there are many — ask user "process next batch?" after every 10 items
