# /ssh-mcp:remove

Remove an SSH host from the MCP session manager, closing any active session first.

## Usage

```
/ssh-mcp:remove <host>
```

## Instructions

You are executing the `/ssh-mcp:remove` command. Follow these steps precisely:

### Step 1: Validate Host Exists

Read the hosts configuration to verify the target host is registered:

```bash
cat ~/.ssh-mcp/hosts.json 2>/dev/null
```

Alternatively, use the MCP tool `list-hosts` to retrieve the host list.

If the host is not found, tell the user:

> Host `<host>` is not configured. Run `/ssh-mcp:list` to see configured hosts.

Stop if the host does not exist.

### Step 2: Check for Active Session

Use the MCP tool `list-sessions` to check if the host has an active session:

```
mcp tool: list-sessions
```

If an active session exists for the target host, close it first:

```
mcp tool: close-session
arguments:
  host: <host>
```

Inform the user:

> Active session on `<host>` closed.

If `close-session` fails, warn the user but continue with removal:

> Warning: Failed to close active session on `<host>`. Proceeding with host removal.

### Step 3: Remove Host

Use the MCP tool `remove-host` to delete the host entry:

```
mcp tool: remove-host
arguments:
  host: <host>
```

If the MCP tool is not available, fall back to editing the file directly:

```bash
# Read ~/.ssh-mcp/hosts.json
# Remove the entry matching <host>
# Write back to ~/.ssh-mcp/hosts.json
```

### Step 4: Confirm Result

Output the result:

```
Host <host> removed.
```

If this was the last host in the configuration, suggest:

> No hosts remaining. Use `/ssh-mcp:add` to configure a new host.

## Important Notes

- Always check for and close active sessions before removing a host
- Never remove a host without first confirming it exists in the configuration
- If `~/.ssh-mcp/hosts.json` becomes empty (no hosts), leave it as a valid JSON object: `{"hosts": []}`
- The remove operation is irreversible -- the host entry and its stored credentials are permanently deleted
