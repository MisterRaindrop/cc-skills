# /review-commit

Review one or more specific commits.

## Usage

```
/review-commit <hash> [<hash2> ...] [--depth quick|standard|deep] [--lang zh|en]
```

**Arguments:**
- `<hash>`: One or more commit hashes or ranges to review
  - Single commit: `abc1234`
  - Multiple commits: `abc1234 def5678`
  - Range: `abc1234..def5678`

**Options:**
- `--depth`: Review depth (default: auto-detected based on change size)
- `--lang`: Output language override (default: auto-detected)

## Instructions

You are executing the `/review-commit` command. Follow these steps:

### Step 1: Parse Arguments

Extract commit hashes and options from user input.

If no hash provided, ask the user:
> Which commit(s) would you like to review? Provide a hash, multiple hashes, or a range.

### Step 2: Validate Commits

For each commit hash:
```bash
# Verify commit exists
git cat-file -t <hash>

# Get commit metadata
git log -1 --format="%H %h %an %s" <hash>
```

For ranges (`A..B`):
```bash
git log --oneline A..B
```

If any commit is invalid, report the error and stop.

### Step 3: Show Review Target

```
## Reviewing Commit(s)

| Hash | Author | Subject |
|------|--------|---------|
| abc1234 | Alice | Add feature X |
| def5678 | Bob | Fix bug Y |

Total changes: <N> files, +<additions> -<deletions>
```

### Step 4: Collect Diff

```bash
DIFF_OUTPUT=$(bash plugins/code-review/scripts/collect-diff.sh commit <hash1> <hash2> ...)
```

### Step 5: Auto-Detect Depth

Same logic as `/review`: count lines, pick depth based on size. Respect `--depth` override.

### Step 6: Delete Previous State and Run Engine

```bash
bash plugins/code-review/scripts/review-state.sh delete 2>/dev/null || true
```

Follow the **review-engine** skill protocol with:
- `target.mode = "commit"`
- `target.commits = [<hashes>]`

### Step 7: Present Results

Same result presentation as `/review`.
