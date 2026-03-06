# Knowledge Archive Skill

Auto-trigger skill for archiving development experiences to Obsidian.

## Auto-trigger

Trigger this skill when the user mentions any of:
- "save this to knowledge base"
- "archive this experience"
- "remember this for next time"
- "save to obsidian"
- "record this finding"
- "archive this session"

When triggered, suggest running `/knowledge:save` to archive the current session's valuable experiences.

## Behavior

When triggered:

1. Briefly summarize what content from the current session looks worth archiving
2. Ask the user if they want to proceed with `/knowledge:save`
3. If yes, execute the full `/knowledge:save` command flow

## Important Notes

- Do NOT auto-archive without user confirmation
- Only suggest archiving when there is genuinely valuable content (bug fixes, architecture decisions, implementation insights)
- Trivial conversations (greetings, simple questions) should NOT trigger this skill
