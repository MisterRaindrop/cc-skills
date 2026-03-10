# /ssh-mcp:setup

First-time install and configure the SSH MCP server (`@iflow-mcp/ssh-mcp-sessions`) for persistent SSH session management.

## Usage

```
/ssh-mcp:setup
```

## Instructions

You are executing the `/ssh-mcp:setup` command. Follow these steps precisely:

### Step 1: Check Prerequisites

Verify Node.js >= 18 and npx are available:

```bash
node --version
npx --version
```

Parse the Node.js version and confirm it is 18 or higher. If Node.js is missing or too old, tell the user:

> Node.js >= 18 is required. Please install or upgrade Node.js before continuing.

Stop if prerequisites are not met.

### Step 2: Test Package Availability

Confirm the `@iflow-mcp/ssh-mcp-sessions` package is accessible:

```bash
npx -y @iflow-mcp/ssh-mcp-sessions --help
```

If this command fails, tell the user:

> Failed to fetch `@iflow-mcp/ssh-mcp-sessions`. Check your network connection and npm registry access.

Stop if the package is not available.

### Step 3: Choose Configuration Location

Ask the user where to register the MCP server:

> Where should the SSH MCP server be configured?
>
> 1. **Project-level** -- write to `.mcp.json` in the current project root (scoped to this project)
> 2. **User-level** -- register via `claude mcp add` (available across all projects)

Wait for the user's response before continuing.

### Step 4: Register MCP Server

**If project-level (option 1):**

Check if `.mcp.json` already exists in the current directory:

```bash
test -f .mcp.json && cat .mcp.json || echo "{}"
```

If it exists, read its contents and merge the new server entry. If it does not exist, create a new file. The resulting `.mcp.json` must contain:

```json
{
  "mcpServers": {
    "ssh-sessions": {
      "command": "npx",
      "args": ["-y", "@iflow-mcp/ssh-mcp-sessions"]
    }
  }
}
```

Preserve any existing `mcpServers` entries when merging.

**If user-level (option 2):**

```bash
claude mcp add ssh-sessions -- npx -y @iflow-mcp/ssh-mcp-sessions
```

Confirm the command succeeds. If it fails, show the error output and suggest the user try project-level configuration instead.

### Step 5: Guide First Host Addition

Tell the user:

> SSH MCP server registered successfully. Let's add your first SSH host.

Invoke the `/ssh-mcp:add` flow to walk the user through adding their first host.

### Step 6: Output Summary

Display a configuration summary:

```
SSH MCP Setup Complete
----------------------
Server:   @iflow-mcp/ssh-mcp-sessions
Config:   <project-level (.mcp.json) | user-level (claude mcp)>
Host(s):  <list of added hosts, or "none yet" if user skipped>

IMPORTANT: Restart Claude Code for the MCP server to become available.
```

## Important Notes

- The MCP server name is always `ssh-sessions` -- do not use a different name
- If `.mcp.json` already contains an `ssh-sessions` entry, ask the user before overwriting
- The `npx -y` flag auto-confirms the install prompt so it works non-interactively
- Remind the user to restart Claude Code at the end -- the MCP server will not be available until then
