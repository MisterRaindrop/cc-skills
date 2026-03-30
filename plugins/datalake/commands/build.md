# /datalake:build

Build datalake components inside the Docker development container.

## Usage

```
/datalake:build [TARGET] [OPTIONS]
```

**Targets:**
- `all` — Build agent + proxy + fdw in order (default)
- `fdw` — Build datalake_fdw only (C/C++ PGXS + CMake agent_cli)
- `agent` — Build datalake_agent only (Java Maven)
- `proxy` — Build datalake_proxy only (C PGXS)
- `clean` — Clean all components
- `status` — Show build status (binary timestamps, coverage state)

**Options:**
- `--coverage` — Enable gcov coverage instrumentation (reconfigure + rebuild)
- `--jobs N` — Parallel build jobs (default: auto-detect inside container)
- `--verbose` — Stream build output to stdout instead of log file (only use when user explicitly requests verbose output)

## Instructions

You are executing the `/datalake:build` command. Follow these steps precisely:

**Important:** All builds execute inside the Docker container. The script auto-detects:
1. Database repo root from CWD (walks up looking for `src/backend/` + `contrib/datalake_fdw/`)
2. Docker container name from `docker-compose.yml` in the umbrella root
3. Path mapping: `basename(DB_ROOT)` → `/workspace/<instance_name>` inside container

### Step 1: Auto-detect Target (if no argument provided)

If no target argument was given, analyze `git diff` to suggest a target:

```bash
git diff --name-only HEAD
```

| Changed path pattern | Suggested target |
|---------------------|-----------------|
| `contrib/datalake_agent/*` | `agent` |
| `contrib/datalake_proxy/*` | `proxy` |
| `contrib/datalake_fdw/*` | `fdw` |
| Multiple `contrib/datalake_*` | `all` |

Show the suggestion and ask the user to confirm, or let them override.

### Step 2: Run the Build

```bash
"${CLAUDE_SKILL_DIR}/../scripts/build.sh" $ARGUMENTS
```

The script automatically redirects compilation output to a timestamped log file under `<umbrella_root>/logs/`. Only progress milestones and the final summary appear in stdout.

- For `all` target: use Bash with `run_in_background: true` (builds all three components sequentially, takes several minutes)
- For single components (`fdw`, `agent`, `proxy`): can run in foreground (usually completes in under 2 minutes)

The script:
1. Detects the database repo root from CWD
2. Derives the Docker path from the worktree name
3. Discovers the container from docker-compose.yml
4. Executes all build commands via `docker exec` inside the container
5. Prints `BUILD SUCCESS` or `BUILD FAILED` summary to stdout

### Step 3: Report Result

```
## Build Complete

Target:    <target>
Instance:  <worktree name>
Container: <container name>
Log file:  <path to log file>

Run `/datalake:test smoke` to verify your changes.
```

### Error Handling

If the build fails (`BUILD FAILED` in output):
1. The script automatically prints the last 30 lines of the build log to stdout — check these for the error.
2. If more context is needed, use the `Read` tool to read the full log file and search for `error:`, `fatal:`, or `undefined reference`.
3. Suggest fixes based on the error type:
   - Compilation error → fix the code, show the relevant source file
   - Maven error (agent) → check network/Maven installation
   - Missing dependency → check if Apache Arrow is pre-built at `contrib/apache-arrow/dist`

**Note:** Only add `--verbose` when the user explicitly requests verbose/streaming output. By default, log redirection keeps Claude's context clean.

### Key Reference

**Build Order:** agent → proxy → fdw
- Agent JAR must be installed to `$(pkglibdir)/java/` first
- FDW links against agent_cli (C REST client)
- datalake_fdw has ~129 object files — `-j$(nproc)` is used for speed

**Coverage:** `--coverage` flag builds datalake components with gcov instrumentation. The database must already be configured with `--enable-coverage` — use `/datalake:build_database --coverage` first.

### Important Notes

- User executes Claude on the **host machine (macOS)** — all builds run inside Docker via `docker exec`
- The worktree name determines which database instance is built (path isolation)
- Apache Arrow (`contrib/apache-arrow/dist`) must be pre-built for fdw compilation
- Coverage builds are significantly slower due to database reconfigure + full rebuild
- Build failures in one component do not block building other components (except dependency order)
