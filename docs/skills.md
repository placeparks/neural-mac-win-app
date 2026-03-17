# Skills Framework

NeuralClaw exposes tools through `SkillManifest`, `ToolDefinition`, and the
`SkillRegistry`.

## Built-in Skills

| Skill | Purpose | Example tools |
|---|---|---|
| `web_search` | search and fetch | `web_search`, `fetch_url` |
| `file_ops` | bounded filesystem access | `read_file`, `write_file`, `list_directory` |
| `code_exec` | sandboxed execution | `execute_python` |
| `calendar_skill` | local calendar operations | `create_event`, `list_events`, `delete_event` |
| `github_repos` | repo management | `clone_repo`, `install_repo_deps`, `list_repos` |
| `repo_exec` | repo-local command execution | `run_repo_script`, `run_repo_command` |
| `api_client` | authenticated outbound APIs | `api_request`, `save_api_config`, `list_api_configs` |
| `tts` | text-to-speech | `speak`, `list_voices`, `speak_and_play` |
| `google_workspace` | Gmail, Calendar, Drive, Docs, Sheets | `gmail_*`, `gcal_*`, `gdrive_*`, `gdocs_*`, `gsheets_*`, `gmeet_create` |
| `microsoft365` | Outlook, Teams, OneDrive, SharePoint | `outlook_*`, `ms_cal_*`, `teams_*`, `onedrive_*`, `sharepoint_*` |

Dynamic tool groups are registered by the gateway only when enabled:

- browser tools
- desktop tools

## Manifest Model

```python
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

manifest = SkillManifest(
    name="my_skill",
    description="Does useful work",
    tools=[
        ToolDefinition(
            name="my_tool",
            description="Example tool",
            parameters=[
                ToolParameter("query", "string", "What to search for"),
            ],
            handler=my_tool,
        )
    ],
)
```

## Capability Model

Important capability groups now include:

- browser control and browser JS
- desktop control
- audio output and voice channel
- Google Workspace capabilities
- Microsoft 365 capabilities

The capability verifier provides default grants for built-ins and blocks
ungranted capabilities at runtime.

## Security Requirements

Builtin skill handlers should:

- return `dict[str, Any]`
- catch failures and return `{"error": "..."}`
- validate outbound URLs through `validate_url_with_dns()`
- rely on policy and idempotency for side-effect safety
