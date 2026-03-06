# Knowledge Maintain Skill

Auto-trigger skill for knowledge base maintenance.

## Auto-trigger

Trigger this skill when the user mentions any of:
- "clean up knowledge base"
- "audit knowledge"
- "check for expired notes"
- "maintain obsidian"
- "knowledge base maintenance"

When triggered, suggest running `/knowledge:maintain`.

## Behavior

When triggered:

1. Inform the user that a maintenance scan is available
2. Ask if they want to proceed with `/knowledge:maintain`
3. If yes, execute the full `/knowledge:maintain` command flow

## Important Notes

- Maintenance is an interactive process — always confirm actions with the user
- Never delete files without double confirmation
