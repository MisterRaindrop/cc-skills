# /review-config

Configure code review preferences.

## Usage

```
/review-config [<setting> <value>]
```

**Without arguments:** Show current configuration.

**Settings:**
- `depth <quick|standard|deep>`: Default review depth
- `lang <auto|zh|en>`: Default output language
- `max-rounds <1-5>`: Maximum challenge rounds

## Instructions

You are executing the `/review-config` command. Follow these steps:

### Step 1: Load Current Config

Check if a config file exists:
```bash
CONFIG_FILE="$(git rev-parse --git-dir 2>/dev/null)/code-review-config.json"
```

If no config file exists, use defaults:
```json
{
  "depth": "auto",
  "lang": "auto",
  "max_rounds": 3
}
```

### Step 2: No Arguments - Show Config

Display current configuration:

```
## Code Review Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| depth | auto | Review depth (auto/quick/standard/deep) |
| lang | auto | Output language (auto/zh/en) |
| max_rounds | 3 | Max challenge rounds (1-5) |

Config location: <config-file-path>

To change: /review-config <setting> <value>
Examples:
  /review-config depth deep
  /review-config lang zh
  /review-config max-rounds 5
```

### Step 3: With Arguments - Update Config

Parse the setting and value:

**depth:**
- Valid values: `auto`, `quick`, `standard`, `deep`
- Invalid value: report error

**lang:**
- Valid values: `auto`, `zh`, `en`
- Invalid value: report error

**max-rounds:**
- Valid values: integer 1-5
- Invalid value: report error

Write updated config:
```bash
# Create or update config file
echo '<updated-json>' | jq '.' > "$CONFIG_FILE"
```

Confirm:
```
Updated: <setting> = <value>
```
