# CC Skills

A collection of plugins (skills) for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

## Available Plugins

### cherry-pick

Smart cherry-pick workflow with three modes:

| Command | What it does |
|---------|-------------|
| `/cherry-pick:commit <hash>` | Quick cherry-pick. Merges the commit, asks about conflicts, review, and commit step by step. |
| `/cherry-pick:plan <hash>` | Careful cherry-pick. Reads the code first, shows you a risk analysis and merge strategy, then executes only after you say yes. |
| `/cherry-pick:batch <source>` | Batch cherry-pick. Give it a branch range or list of commits. It builds a TODO list and walks through each one. Add `--auto` to let it run hands-free. |
| `/cherry-pick:review` | Multi-agent code review (CoderA + CoderB) for the current cherry-pick result. |

### knowledge

Obsidian-powered knowledge management. Turns Obsidian into Claude Code's long-term memory.

| Command | What it does |
|---------|-------------|
| `/knowledge:save` | Archive this session's experiences (bug fixes, architecture decisions, debug insights) to your Obsidian vault. Auto-classifies, generates frontmatter, updates indexes. |
| `/knowledge:maintain` | Scan the vault for expired notes, inbox backlog, and missing metadata. Interactively clean up. |

**Requires**: Obsidian with Local REST API + MCP Tools plugins. See [knowledge plugin README](plugins/knowledge/README.md) for setup.

### code-review

Multi-agent adversarial code review with dual-team architecture.

| Command | What it does |
|---------|-------------|
| `/code-review:review` | Review current changes with multi-agent discussion. |
| `/code-review:review-commit` | Review a specific commit. |
| `/code-review:review-branch` | Review an entire branch diff. |
| `/code-review:review-config` | Configure review settings. |

### pxf

PXF development automation for Cloudberry PXF. Docker environment, build, test, result parsing.

| Command | What it does |
|---------|-------------|
| `/pxf:docker-up` | Start Docker dev environment (Cloudberry + Hadoop + Hive + HBase + MinIO) |
| `/pxf:docker-down` | Stop/clean Docker environment |
| `/pxf:build [target]` | Build PXF (all, server, quick, single module like pxf-hdfs) |
| `/pxf:test [group]` | Run automation tests by group with optional test filter |
| `/pxf:parse-results` | Parse surefire XML reports into summary table |

**Requires**: Docker, [cloudberry-pxf](https://github.com/apache/cloudberry-pxf) repo with `dev/` scripts. See [pxf plugin README](plugins/pxf/README.md) for details.

### finish-mr

Owns one exact GitLab merge request from finished implementation until it is merged, closed,
merge-ready, or genuinely blocked. Creating the MR or pushing once is not completion.

| Skill | What it does |
|-------|-------------|
| `finish-mr` | Writes the MR title and description as the final squash commit message, checks every commit message, the changed lines' code style and the license headers against Apache project conventions (50/72 commit format, ASF header, no incompatible licenses), verifies each review suggestion before acting, retries a flaky CI job at most once, rebases with `--force-with-lease`, re-verifies every new HEAD, arms a background watcher (`scripts/watch_mr.py`) so hours-long pipelines are followed without a prompt, and ends with `FINISH_READY` / `FINISH_WAITING` / `FINISH_MERGED` / `FINISH_CLOSED` / `FINISH_BLOCKED`. It never merges the MR itself. |

**GitLab only.** It is invoked by the model when you ask it to finish an MR, not as a slash command.

---

## Installation

There are three ways to install these plugins. Pick whichever works for you.

### Option A: Quick Test (no install needed)

Just want to try a plugin? Use the `--plugin-dir` flag. Nothing is installed permanently.

```bash
# 1. Clone this repo
git clone https://github.com/MisterRaindrop/cc-skills.git
cd cc-skills

# 2. Run Claude Code with the plugin loaded directly
claude --plugin-dir ./plugins/cherry-pick

# That's it. The plugin is active for this session only.
# You can load multiple plugins at once:
claude --plugin-dir ./plugins/cherry-pick --plugin-dir ./plugins/knowledge
```

When you close Claude Code, the plugins are gone. No cleanup needed.

### Option B: Install from Local Marketplace (persistent)

This installs the plugins permanently so they're always available.

```bash
# 1. Clone this repo somewhere permanent
git clone https://github.com/MisterRaindrop/cc-skills.git ~/cc-skills
```

```bash
# 2. Start Claude Code
claude
```

```
# 3. Inside Claude Code, add this repo as a marketplace
/plugin marketplace add ~/cc-skills
```

Claude Code reads the `.claude-plugin/marketplace.json` file and discovers all available plugins.

```
# 4. Install the plugins you want
/plugin install cherry-pick@cc-skills-marketplace
/plugin install knowledge@cc-skills-marketplace
/plugin install code-review@cc-skills-marketplace
```

You can choose the install scope:
- **user** (default) -- available everywhere, for just you
- **project** -- available only in the current git repo
- **local** -- available only in the current directory

```
# Example: install only for the current project
/plugin install cherry-pick@cc-skills-marketplace --scope project
```

### Option C: Install from GitHub (no clone needed)

Skip the clone entirely. Point Claude Code straight at the GitHub repo.

```bash
# 1. Start Claude Code
claude
```

```
# 2. Add the GitHub repo as a marketplace
/plugin marketplace add MisterRaindrop/cc-skills
```

```
# 3. Install plugins
/plugin install cherry-pick@cc-skills-marketplace
/plugin install knowledge@cc-skills-marketplace
/plugin install code-review@cc-skills-marketplace
```

### Verify It Worked

Start a new Claude Code session and type `/`. You should see your installed plugins' commands in the list:

```
/cherry-pick:commit
/cherry-pick:plan
/cherry-pick:batch
/cherry-pick:review
/knowledge:save
/knowledge:maintain
/code-review:review
...
```

If you don't see them, run `/plugin` to open the plugin manager and check the installed list.

### Uninstall

```
/plugin uninstall cherry-pick
```

---

## Extra Setup for the Knowledge Plugin

The knowledge plugin needs Obsidian running with two community plugins. This is a one-time setup.

### 1. Install Obsidian

Download from [obsidian.md](https://obsidian.md) if you don't have it. Create or open a vault.

### 2. Install the Local REST API plugin

1. Open Obsidian
2. Go to **Settings** > **Community Plugins** > **Browse**
3. Search for **Local REST API**
4. Click **Install**, then **Enable**
5. In the plugin settings, enable **Non-encrypted (HTTP) Server**
6. Note the **API Key** it generates -- you'll need it later
7. Test: open `http://localhost:27123` in your browser. You should see the API docs page.

### 3. Install the MCP Tools plugin

**Do this AFTER Local REST API is installed and enabled. Order matters.**

1. In Community Plugins, search for **MCP Tools**
2. Click **Install**, then **Enable**
3. In the plugin settings, paste the **API Key** from step 2
4. The plugin creates a file at: `<your-vault>/.obsidian/plugins/mcp-tools/bin/mcp-server`
5. Make it executable:
   ```bash
   chmod +x <your-vault>/.obsidian/plugins/mcp-tools/bin/mcp-server
   ```

### 4. Connect Claude Code to Obsidian

Edit `~/.claude.json` and add this block at the top level:

```json
{
  "mcpServers": {
    "obsidian": {
      "type": "stdio",
      "command": "<your-vault>/.obsidian/plugins/mcp-tools/bin/mcp-server",
      "args": [],
      "env": {
        "OBSIDIAN_API_KEY": "<your-api-key-from-step-2>",
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1"
      }
    }
  }
}
```

Replace `<your-vault>` with the absolute path to your Obsidian vault, and `<your-api-key-from-step-2>` with the actual API key.

### 5. Test the connection

```bash
claude mcp list
```

You should see `obsidian` with a green checkmark. If it says "Failed to connect":
- Is Obsidian open?
- Is Local REST API enabled?
- Is the path to `mcp-server` correct?
- Is the API key correct?

### 6. Create the vault directory structure

Inside your Obsidian vault, create:

```
Knowledge/
├── _taxonomy.md          <-- classification rules (see below)
├── _inbox/
│   └── README.md
├── Projects/
│   └── (your project folders will go here)
└── Patterns/
    └── _index.md
```

### 7. Create the classification rules file

Create `Knowledge/_taxonomy.md` in your vault. This file tells Claude how to organize your notes.

A minimal version:

```markdown
# Knowledge Classification Rules

> Read before every /knowledge:save execution.

## Classification

| Content Type | Location |
|-------------|----------|
| Dev experience, architecture decisions | `Projects/{project}/development/` |
| Bug analysis, troubleshooting | `Projects/{project}/troubleshooting/` |
| Unknown project | `_inbox/` |

## Frontmatter

Every note needs:
- title, date, project, tags
- status: active / archived / outdated
- content_type: permanent / session / plan / todo / snapshot
- review_after: date + days based on content_type

## review_after Rules

| content_type | Days |
|-------------|------|
| permanent | +180 |
| session | +30 |
| plan | +7 |
| todo | +14 |
| snapshot | +30 |

## Naming

`YYYY-MM-DD-short-description.md`
```

Customize this for your projects. See [knowledge plugin README](plugins/knowledge/README.md) for the full version.

### 8. Done

You're all set. Try it:

```
claude
> /knowledge:save
```

If the current session has valuable content, Claude will archive it to your vault.

---

## License

MIT
