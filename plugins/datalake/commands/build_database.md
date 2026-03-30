# /datalake:build_database

Compile the full Greenplum/Cloudberry database inside the Docker development container (configure + make + install).

## Usage

```
/datalake:build_database [OPTIONS]
```

**Options:**
- `--clean` — Clean build: reconfigure from scratch
- `--coverage` — Enable gcov coverage instrumentation (`--enable-coverage`)
- `--debug` — Debug build with assertions (default)
- `--release` — Release build (optimized, no assertions)
- `--jobs N` — Parallel build jobs (default: auto-detect inside container)
- `--verbose` — Stream build output to stdout instead of log file (only use when user explicitly requests verbose output)

## Instructions

You are executing the `/datalake:build_database` command. Follow these steps precisely:

**Important:** This compiles the **entire database**, not just datalake components. Use `/datalake:build` for datalake-only compilation.

### Step 1: Run the Script

Run the build script in the background since database builds take 10-30 minutes:

```bash
"${CLAUDE_SKILL_DIR}/../scripts/build-database.sh" $ARGUMENTS
```

Use Bash with `run_in_background: true` for this command. The script automatically redirects compilation output to a timestamped log file under `<umbrella_root>/logs/`. Only progress milestones and the final summary appear in stdout.

The script:
1. Detects database repo root from CWD
2. Derives instance name from worktree directory name
3. Discovers container from docker-compose.yml
4. Installs dependencies if needed (conan/thirdparty)
5. Configures the database (with `--coverage` if requested)
6. Compiles and installs to `/workspace/dist/<instance>`
7. Prints `BUILD SUCCESS` or `BUILD FAILED` summary to stdout

### Step 2: Wait for Completion

Wait for the background task to complete. Check the output for `BUILD SUCCESS` or `BUILD FAILED`.

### Step 3: Report Result

```
## Database Build Complete

Instance:   <worktree name>
Build type: <debug|release>
Coverage:   <yes|no>
Install:    /workspace/dist/<instance>
Log file:   <path to log file>

Next: Run `/datalake:initdb` to deploy a cluster.
```

### Error Handling

If the build fails (`BUILD FAILED` in output):
1. The script automatically prints the last 30 lines of the build log to stdout — check these for the error.
2. If more context is needed, use the `Read` tool to read the full log file and search for `error:`, `fatal:`, or `undefined reference`.
3. Suggest fixes based on the error type:
   - Configure error → check dependencies, try `--clean`
   - Compilation error → show the relevant source file and error
   - Dependency error (conan) → check network in container

**Note:** Only add `--verbose` when the user explicitly requests verbose/streaming output. By default, log redirection keeps Claude's context clean.

### Typical Workflows

**Normal development:**
```
/datalake:build_database
/datalake:initdb
/datalake:build fdw
/datalake:test smoke
```

**Coverage development:**
```
/datalake:build_database --clean --coverage
/datalake:initdb
/datalake:build all --coverage
/datalake:test all
/datalake:coverage collect
```

### Important Notes

- User executes Claude on the **host machine (macOS)** — compilation runs inside Docker via `docker exec`
- `--coverage` reconfigures with `--enable-coverage` + `CFLAGS="-O0 -g3"` — significantly slower
- `--clean` forces a full reconfigure, useful when switching between normal/coverage builds
- This command does NOT deploy a cluster — use `/datalake:initdb` after building
- Build takes 10-30 minutes depending on `--clean` and machine specs
