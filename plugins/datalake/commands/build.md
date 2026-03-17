# /datalake:build

Build and install datalake components: datalake_fdw (C/C++ FDW extension), datalake_agent (Java Spring Boot), datalake_proxy (C background worker), or all three.

## Usage

```
/datalake:build [fdw|agent|proxy|all|coverage|clean|status]
```

**Arguments:**
- `fdw` — Build datalake_fdw only (C/C++ PGXS + CMake agent_cli)
- `agent` — Build datalake_agent only (Java Maven)
- `proxy` — Build datalake_proxy only (C PGXS)
- `all` — Build all three components in order: agent → proxy → fdw (default)
- `coverage` — Rebuild with `--enable-coverage` for gcov instrumentation
- `clean` — `make clean` all three components
- `status` — Show build status of each component
- *(no argument)* — Same as `all`

## Instructions

You are executing the `/datalake:build` command. Follow these steps precisely:

**Important:** The database source root is:
```
/Volumes/ZHITAITiPlus71002TBMedia/liuxiaoyu/git/hashdata-lightning-umbrella2/hashdata-lightning-umbrella/database
```
Store this as `DB_ROOT`.

### Key Reference Information

**Component Paths:**

| Component | Path | Build System | Output |
|-----------|------|-------------|--------|
| datalake_fdw | `$DB_ROOT/contrib/datalake_fdw` | PGXS + CMake (agent_cli) | `datalake_fdw.so` |
| datalake_agent | `$DB_ROOT/contrib/datalake_agent` | Maven (`mvn package -DskipTests`) | `target/dlagent-1.0.0.jar` |
| datalake_proxy | `$DB_ROOT/contrib/datalake_proxy` | PGXS | `datalake_proxy.so` |

**Build Order:** `datalake_agent` → `datalake_proxy` → `datalake_fdw`
- Agent JAR must be installed to `$(pkglibdir)/java/` first
- Proxy manages the agent Java process at runtime
- FDW links against agent_cli (C REST client to communicate with agent)

**Dependencies:**
- datalake_fdw links: `-lgopher -lparquet -lorc -larchive -lavrocpp -larrow -lavro -lcurl -lyaml -lboost_iostreams -lsnappy -lprotobuf -lstdc++`
- Apache Arrow must be pre-built: `$DB_ROOT/contrib/apache-arrow/dist`
- datalake_fdw includes agent_cli CMake subproject: `src/components/agent_cli/`
- datalake_agent requires Maven (`mvn`)
- libjansson.a must be available (static linking)

**Key Makefiles:**
- `contrib/datalake_fdw/Makefile` — 129 object files, PGXS + agent_cli CMake
- `contrib/datalake_agent/Makefile` — Maven wrapper, installs JAR to `$(pkglibdir)/java/`
- `contrib/datalake_proxy/Makefile` — Single file (`datalake_proxy.c`), PGXS

---

### Step 1: Parse Arguments

Determine the build target. Default to `all` if no argument provided.

### Step 2: Execute Build

#### Build Agent (Java/Maven)

```bash
cd $DB_ROOT/contrib/datalake_agent
make clean
make
make install
```

This runs `mvn package -DskipTests` and installs `target/dlagent-1.0.0.jar` to `$(pkglibdir)/java/`.

Record exit code and duration.

If the build fails, show the error and ask the user:

> Agent build failed. Retry, skip, or show full log?

#### Build Proxy (C/PGXS)

```bash
cd $DB_ROOT/contrib/datalake_proxy
make clean
make
make install
```

Record exit code and duration. Follow the same retry/skip flow on failure.

#### Build FDW (C/C++ PGXS + CMake)

```bash
cd $DB_ROOT/contrib/datalake_fdw
make clean
make -j$(nproc)
make install
```

This will:
1. Build the `agent_cli` CMake subproject (creates `libagent_cli.a`)
2. Compile all 129 object files
3. Link `datalake_fdw.so` with all dependencies
4. Install to `$(pkglibdir)`

Record exit code and duration. Follow the same retry/skip flow on failure.

---

### Subcommand: `coverage`

Rebuild everything with gcov coverage instrumentation.

#### Step 1: Check Current Coverage State

```bash
grep 'enable_coverage' $DB_ROOT/src/Makefile.global || echo "Coverage not enabled"
```

#### Step 2: Reconfigure if Needed

If `enable_coverage` is not set or is `no`, the database needs reconfiguring:

```bash
cd $DB_ROOT
# Re-run configure with --enable-coverage plus existing options
# Reference: devops/build/automation/cloudberry/scripts/configure-cloudberry.sh
./configure --enable-coverage \
  --with-perl --with-python --with-libxml --with-gssapi \
  --enable-mapreduce --enable-orafce --enable-tap-tests \
  --enable-debug --enable-cassert \
  --prefix=/usr/local/cloudberry-db \
  CFLAGS="-O0 -g3" CXXFLAGS="-O0 -g3"
```

**Important:** Ask the user before reconfiguring — this is a heavyweight operation that rebuilds the entire database.

#### Step 3: Full Database Rebuild

```bash
cd $DB_ROOT
make -j$(nproc)
make install
```

#### Step 4: Build All Three Components

Build agent → proxy → fdw in sequence (same as `all`).

For FDW with coverage, also pass coverage flags to agent_cli CMake:
```bash
cd $DB_ROOT/contrib/datalake_fdw/src/components/agent_cli
mkdir -p build && cd build
cmake .. -DCMAKE_C_FLAGS="--coverage" -DCMAKE_CXX_FLAGS="--coverage"
make
```

#### Step 5: Verify Coverage

```bash
find $DB_ROOT/contrib/datalake_fdw/src -name "*.gcno" | wc -l
find $DB_ROOT/contrib/datalake_proxy -name "*.gcno" | wc -l
```

Report the count of `.gcno` files. Note: datalake_agent is Java — gcov does not apply.

---

### Subcommand: `clean`

```bash
cd $DB_ROOT/contrib/datalake_agent && make clean
cd $DB_ROOT/contrib/datalake_proxy && make clean
cd $DB_ROOT/contrib/datalake_fdw && make clean
```

---

### Subcommand: `status`

Check the build status of each component:

```bash
# Check datalake_fdw.so
ls -la $(pg_config --pkglibdir)/datalake_fdw.so 2>/dev/null

# Check dlagent-1.0.0.jar
ls -la $(pg_config --pkglibdir)/java/dlagent-1.0.0.jar 2>/dev/null

# Check datalake_proxy.so
ls -la $(pg_config --pkglibdir)/datalake_proxy.so 2>/dev/null

# Check coverage (.gcno files)
FDW_GCNO=$(find $DB_ROOT/contrib/datalake_fdw/src -name "*.gcno" 2>/dev/null | wc -l)
PROXY_GCNO=$(find $DB_ROOT/contrib/datalake_proxy -name "*.gcno" 2>/dev/null | wc -l)
```

Display:

```
## Datalake Build Status

| Component       | Binary              | Last Modified        | Coverage           |
|-----------------|---------------------|----------------------|--------------------|
| datalake_fdw    | datalake_fdw.so     | 2026-03-17 14:30     | yes (120 .gcno)    |
| datalake_agent  | dlagent-1.0.0.jar   | 2026-03-17 14:25     | N/A (Java)         |
| datalake_proxy  | datalake_proxy.so   | 2026-03-17 14:28     | yes (1 .gcno)      |
```

---

### Step 3: Output Build Summary

After all builds complete:

```
## Datalake Build Summary

| Component       | Status  | Duration |
|-----------------|---------|----------|
| datalake_agent  | success | 45s      |
| datalake_proxy  | success | 3s       |
| datalake_fdw    | success | 30s      |

Build complete. Run `/datalake:test smoke` to verify.
```

### Important Notes

- Build order matters: agent → proxy → fdw (agent JAR must exist for proxy runtime, agent_cli lib must link for fdw)
- datalake_fdw has ~129 object files — `make -j$(nproc)` is recommended for speed
- The agent_cli CMake subproject is built automatically by the fdw Makefile
- Apache Arrow (`contrib/apache-arrow/dist`) must be pre-built for fdw compilation
- datalake_agent requires Maven (`mvn`) — if not found, the build will fail
- datalake_proxy is a single-file build (`datalake_proxy.c`, ~272 lines)
- Coverage builds require `--enable-coverage` in the database configure — this triggers a full rebuild
- Build failures in one component do not block building other components (except dependency order)
- Keep output concise — show build status and errors, not full compilation logs
