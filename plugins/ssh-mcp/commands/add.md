# /ssh-mcp:add

Add an SSH host to the MCP session manager with connection testing and credential configuration.

## Usage

```
/ssh-mcp:add <host> --user <user> [--port 22] [--password <pass> | --key <path>]
```

## Instructions

You are executing the `/ssh-mcp:add` command. Follow these steps precisely:

### Step 1: Parse Arguments

Extract parameters from the user's input:

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `host` | Yes | -- | Hostname or IP address |
| `--user` | Yes | -- | SSH username |
| `--port` | No | `22` | SSH port |
| `--password` | No | -- | Password (mutually exclusive with `--key`) |
| `--key` | No | -- | Path to SSH private key file |

If `host` or `--user` is missing, ask the user interactively:

> Please provide the missing connection details:
> - **Host**: (hostname or IP)
> - **User**: (SSH username)

If neither `--password` nor `--key` is provided, proceed to Step 2 to suggest options.

### Step 2: Scan SSH Config for Suggestions

Run the detect-targets script to find known hosts:

```bash
bash "$(dirname "$0")/../scripts/detect-targets.sh"
```

Alternatively, parse `~/.ssh/config` directly for Host entries. If the target host is found in SSH config, inform the user:

> Found `<host>` in your SSH config with user=`<user>`, port=`<port>`. Use these settings?

If no auth method was provided, check for available SSH keys:

```bash
ls -1 ~/.ssh/id_* 2>/dev/null | grep -v '\.pub$'
```

If keys are found, suggest using key-based authentication:

> Found SSH keys: `<list of keys>`. Would you like to use one of these?

If no keys are found and no password was provided, ask:

> No SSH keys found. Please provide an authentication method:
> 1. **Password** -- enter password (will be stored in hosts config)
> 2. **Key path** -- provide path to a private key file

Wait for the user's response.

### Step 3: Test Connection

Test SSH connectivity with a timeout:

```bash
ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -p <port> <user>@<host> echo "CONNECTION_OK"
```

If using key-based auth:

```bash
ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i <key-path> -p <port> <user>@<host> echo "CONNECTION_OK"
```

- **Connection succeeds**: Proceed to Step 4.
- **Connection fails**: Show the error and ask the user if they want to add the host anyway:

> Connection test failed: `<error message>`
>
> Add this host anyway? (You can fix connectivity later.)

Wait for the user's response. Stop if they say no.

### Step 4: Security Warning for Password Auth

If the user chose password authentication, display a warning:

> **Security Warning**: Password authentication stores credentials in `~/.ssh-mcp/hosts.json` in plain text. This is less secure than key-based authentication.
>
> Recommendations:
> - Use SSH key authentication instead (`ssh-keygen -t ed25519`)
> - Ensure `~/.ssh-mcp/hosts.json` has restrictive permissions (`chmod 600`)
>
> Continue with password auth?

Wait for the user's response. If they say no, ask them to provide a key path instead.

### Step 5: Add Host via MCP

Use the MCP tool `add-host` to register the host:

```
mcp tool: add-host
arguments:
  host: <host>
  username: <user>
  port: <port>
  authMethod: "key" | "password"
  privateKeyPath: <key-path>   (if key auth)
  password: <password>          (if password auth)
```

If the MCP tool is not available (server not running), fall back to writing directly:

```bash
mkdir -p ~/.ssh-mcp
# Read existing hosts.json or create new
# Add the new host entry
# Write back to ~/.ssh-mcp/hosts.json
chmod 600 ~/.ssh-mcp/hosts.json
```

### Step 6: Confirm Result

Output the result:

```
Host <host> added successfully.
  User: <user>
  Port: <port>
  Auth: <key | password>
```

If this is the first host being added, suggest testing with a command:

> Try running a remote command: ask Claude to execute something on `<host>` via the SSH MCP session.

## Important Notes

- Always test connectivity before adding unless the user explicitly skips
- Never echo passwords to the terminal or include them in command output
- If `--key` path is relative, resolve it to an absolute path before storing
- The `--password` and `--key` flags are mutually exclusive -- if both are provided, ask the user to choose one
- `~/.ssh-mcp/hosts.json` must have `600` permissions to protect credentials
