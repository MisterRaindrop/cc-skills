# /ssh-mcp:list

List all configured SSH hosts and their active session status in a readable table.

## Usage

```
/ssh-mcp:list
```

## Instructions

You are executing the `/ssh-mcp:list` command. Follow these steps precisely:

### Step 1: Read Host Configuration

Read the hosts configuration file:

```bash
cat ~/.ssh-mcp/hosts.json 2>/dev/null
```

Alternatively, use the MCP tool `list-hosts` to retrieve the full host list:

```
mcp tool: list-hosts
```

If neither source is available or the host list is empty, tell the user:

> No SSH hosts configured. Use `/ssh-mcp:add` to add your first host.

Stop if no hosts are found.

### Step 2: Query Active Sessions

Use the MCP tool `list-sessions` to get all active sessions:

```
mcp tool: list-sessions
```

Match each active session to its corresponding host entry. A session is considered active if the MCP server reports it as connected.

If the MCP server is not reachable, note this in the output:

> Note: SSH MCP server is not running. Session status unavailable.

In this case, show `?` in the Session column instead of `active` or `--`.

### Step 3: Present Results

Output a status table with all configured hosts:

```
| Host       | Port | User | Auth     | Session |
|------------|------|------|----------|---------|
| 10.0.1.5   | 22   | root | key      | active  |
| ci.local   | 22   | ci   | password | --      |
| db.staging | 5422 | dba  | key      | active  |
```

Column definitions:

| Column | Description |
|--------|-------------|
| Host | Hostname or IP address |
| Port | SSH port number |
| User | SSH username |
| Auth | Authentication method: `key` or `password` |
| Session | `active` if a live session exists, `--` if not, `?` if unknown |

### Step 4: Show Summary

After the table, output a summary line:

```
<total> host(s) configured, <active> active session(s).
```

If there are active sessions with idle time information available, append:

```
Longest idle: <host> (<duration>)
```

## Important Notes

- Always show all configured hosts, even if the MCP server is not running
- Sort hosts alphabetically by hostname for consistent output
- If a host has multiple sessions (edge case), show the most recent one
- The `password` auth type should be displayed as `password`, not the actual password value -- never expose credentials in output
