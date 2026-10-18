# Tool registry

Whatever your `kb.json` names, and nothing else: the MCP server in `mcp_server` is attached with
`--mcp-config` under `server_name`, everything else is stripped by `--strict-mcp-config`, and only
the listed `tools` are allowed (`mcp__<server_name>__<tool>`). See
[connection.py](connection.py) for the file format and the repo's `kb.example.json` for a template.

Pick read-only search tools: something that finds notes by keyword or meaning, and optionally
something that resolves a person, company or project name. If your tools report match quality, say
in `instructions` how to read it (for example "use only results whose confidence is strong").

Permission mode `dontAsk`: only the listed tools run; anything else is denied without prompting.
List read-only tools only, so there is no ordering constraint.
