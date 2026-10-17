# Tool registry

Static, two tools from the notes-kb server (`https://kb.example.com/mcp`, attached with
`--mcp-config`, everything else stripped by `--strict-mcp-config`):

| Tool | Use |
|---|---|
| `mcp__notes-kb__search_memories` | Hybrid keyword + semantic search over notes. Returns a `confidence` verdict (strong / weak / keyword / none) that must be read before trusting results. |
| `mcp__notes-kb__find_entity` | Resolve a person, company or project name to a KB entity. |

Permission mode `dontAsk`: only these two run; anything else is denied without prompting. Read-only,
so there is no ordering constraint.
