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

---

## Installation

### Step 1: Clone this repo

```bash
git clone https://github.com/MisterRaindrop/cc-skills.git
```

Pick a location you won't accidentally delete. The path doesn't matter.

### Step 2: Open Claude Code settings

Run Claude Code, then open the settings menu:

```
claude
```

Then type `/settings` and press Enter.

### Step 3: Add this repo as a plugin source

In the settings, navigate to **Plugins** (or **Skills**). Add this repo's local path as a plugin source:

```
/path/to/where/you/cloned/cc-skills
```

Claude Code will scan the `.claude-plugin/marketplace.json` file and discover all available plugins.

### Step 4: Install the plugins you want

After adding the source, you'll see the available plugins listed. Select the ones you want to install:

- **cherry-pick** -- no extra setup needed
- **code-review** -- no extra setup needed
- **knowledge** -- requires Obsidian configuration (see below)

### Step 5: Verify

Start a new Claude Code session and type `/` to see available commands. You should see your installed plugins' commands (e.g., `/cherry-pick:commit`, `/knowledge:save`).

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
