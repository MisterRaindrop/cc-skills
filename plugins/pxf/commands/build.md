# /pxf:build

Build and deploy PXF components inside the pxf-cbdb-dev Docker container.

## Usage

```
/pxf:build [TARGET] [--no-restart]
```

**Targets:**
- `all` — Full build: `make all && make install` (default)
- `server` — Server only: `gradlew stage -x test && make install-server`
- `quick` — Quick install: `make install-server` (skip compilation, just deploy)
- `pxf-hdfs` — Single Gradle module: `:pxf-hdfs:build -x test && make install-server`
- `pxf-jdbc` — Single Gradle module: `:pxf-jdbc:build -x test && make install-server`
- `pxf-hive` — Single Gradle module: `:pxf-hive:build -x test && make install-server`
- `pxf-hbase` — Single Gradle module: `:pxf-hbase:build -x test && make install-server`
- `pxf-json` — Single Gradle module: `:pxf-json:build -x test && make install-server`
- `pxf-s3` — Single Gradle module: `:pxf-s3:build -x test && make install-server`
- `extensions` — Extensions only: `make extensions && make install`
- `test` — Run unit tests: `make test`

**Options:**
- `--no-restart` — Skip PXF restart after build

## Instructions

You are executing the `/pxf:build` command. Follow these steps precisely:

### Step 1: Auto-detect Target (if no argument provided)

If no target argument was given, analyze `git diff` to suggest a target:

```bash
git diff --name-only HEAD
```

| Changed path pattern | Suggested target |
|---------------------|-----------------|
| `server/pxf-hdfs/` | `pxf-hdfs` |
| `server/pxf-jdbc/` | `pxf-jdbc` |
| `server/pxf-hive/` | `pxf-hive` |
| `server/` (multiple modules) | `server` |
| `cli/` | `all` |
| `fdw/` or `external-table/` | `extensions` |
| Multiple areas | `all` |

Show the suggestion and ask the user to confirm, or let them override.

### Step 2: Run the Build

```bash
"${CLAUDE_SKILL_DIR}/../scripts/build.sh" $ARGUMENTS
```

The script:
1. Locates the cloudberry-pxf repo automatically
2. Runs the build command via `docker exec` inside `pxf-cbdb-dev`
3. Automatically restarts PXF after build (unless `--no-restart`)

### Step 3: Report Result

```
## Build Complete

Target:  <target>
PXF:     restarted

Run `/pxf:test` to verify your changes.
```

If the build fails, show the error and suggest:
- Check if it's a compilation error → fix the code
- Check if it's a dependency issue → try `all` target for a clean build

### Important Notes

- All builds run inside the `pxf-cbdb-dev` container via `docker exec`
- The `quick` target is fastest — just deploys pre-built binaries without recompilation
- Single module builds (e.g., `pxf-hdfs`) are the sweet spot for iterative development
- PXF is automatically restarted after build to pick up new binaries
