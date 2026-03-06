# /knowledge:save

Archive development experiences, pitfall records, or architecture decisions from this session to the Obsidian knowledge base.

## Usage

```
/knowledge:save
```

## Prerequisites

- Obsidian must be running with Local REST API and MCP Tools plugins enabled
- MCP connection to Obsidian must be configured (see plugin README)
- `Knowledge/_taxonomy.md` must exist in the vault

## Instructions

You are executing the `/knowledge:save` command. Follow these steps precisely:

### Step 1: Read Classification Rules

Use `mcp__obsidian__get_vault_file` to read `Knowledge/_taxonomy.md`. This file contains:
- Archive location rules
- Frontmatter specification
- Naming conventions
- Update rules

You MUST read this file before proceeding.

### Step 2: Identify Project Name

Derive the project name from the current working directory (`$PWD`):
- Take the last meaningful segment of the path
- If the last segment is a common subdirectory (`src`, `lib`, `fdw`, `cmd`), take the parent instead
- Example: `/home/user/projects/my-app/src` -> project name: `my-app`
- If the project cannot be identified -> archive to `Knowledge/_inbox/`

### Step 3: Scan Existing Notes

Use `mcp__obsidian__list_vault_files` to list all files under `Knowledge/Projects/{project-name}/`.

### Step 4: Search for Similar Content

Use `mcp__obsidian__search_vault_smart` to find notes related to the current session's topic.

- **High similarity found** -> choose **append** mode (add to existing note)
- **No similar notes** -> choose **create** mode (new file)

### Step 5: Determine content_type and review_after

Infer `content_type` from the session content:

| Condition | content_type |
|-----------|--------------|
| Architecture decisions, debug root cause analysis, core design insights | `permanent` |
| Plan files or task planning | `plan` |
| TODO lists or task tracking | `todo` |
| Documentation/README/config snapshots | `snapshot` |
| Implementation records from a session (default) | `session` |

Calculate `review_after` from today's date:

| content_type | Days to add |
|--------------|-------------|
| `permanent` | +180 days |
| `session` | +30 days |
| `plan` | +7 days |
| `todo` | +14 days |
| `snapshot` | +30 days |

### Step 6: Archive Content

**Creating a new note:**

Path pattern:
- Dev experience: `Knowledge/Projects/{project}/development/YYYY-MM-DD-short-description.md`
- Troubleshooting: `Knowledge/Projects/{project}/troubleshooting/YYYY-MM-DD-short-description.md`

Must include complete YAML frontmatter:
```yaml
---
title: Concise title
date: YYYY-MM-DD
project: project-name
tags: [tag1, tag2]
source: claude-code-session
status: active
confidence: high
content_type: session
review_after: YYYY-MM-DD
---
```

Recommended content structure:
- `## Background` — problem/task origin
- `## Key Findings` — core knowledge points with code blocks
- `## Solution` — specific approach taken
- `## References` — file paths (with line numbers), commits, doc links

**Appending to an existing note:**
- Append new content at the end, separated by `---`
- Update the `date` field in frontmatter to today

Use `mcp__obsidian__create_vault_file` for new notes or `mcp__obsidian__append_to_vault_file` for appending.

### Step 7: Update Project Index

Use `mcp__obsidian__patch_vault_file` to update `Knowledge/Projects/{project}/_index.md`:
- Add a wikilink under the appropriate section (Development or Troubleshooting)
- Format: `- [[filename-without-extension|Note Title]]`

### Step 8: Evaluate Cross-Project Reuse Value

If the experience has cross-project generalizability:
- Add a wikilink in `Knowledge/Patterns/_index.md` under the relevant category

### Step 9: Evaluate Wiki Distillation

| Condition | Action |
|-----------|--------|
| Involves general technical concepts (FDW, MVCC, vectorized execution, etc.) | Generate Wiki draft in `Knowledge/_inbox/` |
| Project-specific implementation details | Skip |

Draft path: `Knowledge/_inbox/YYYY-MM-DD-{concept-name}-draft.md`

### Step 10: Report Results

Output an archive summary:
```
Archive complete:
- [created/updated] Knowledge/Projects/{project}/development/YYYY-MM-DD-xxx.md | content_type: session | review_after: YYYY-MM-DD
- [updated] Knowledge/Projects/{project}/_index.md
- [updated] Knowledge/Patterns/_index.md (if applicable)
- [created] Knowledge/_inbox/YYYY-MM-DD-xxx-draft.md (if applicable)
```

## Important Notes

- **Quality over quantity**: Only archive knowledge with reuse value
- **Complete code snippets**: Key code must be directly reusable
- **Precise paths**: Record source file paths with line numbers
- **content_type is mandatory**: Every new note must include it
- **Search before creating**: Always check for similar notes first to avoid duplicates
