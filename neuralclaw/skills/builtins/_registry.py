"""
Static metadata registry for all built-in skills.

Used by SkillRegistry.load_builtins() to register tool stubs without
importing the actual skill modules. Heavy modules are only imported
when a tool from that skill is first invoked (lazy loading).
"""

from __future__ import annotations

BUILTIN_SKILL_METADATA: list[dict] = [
    {
        "module": "neuralclaw.skills.builtins.web_search",
        "name": "web_search",
        "description": "Search the web and extract page content using multiple providers",
        "tools": [
            {
                "name": "web_search",
                "description": "Search the web for information. Uses the best available provider (Brave > Google > SearXNG > DuckDuckGo) with automatic fallback.",
                "parameters": {"query": {"type": "string", "description": "Search query"}, "max_results": {"type": "integer", "description": "Maximum results to return (default 5)"}},
                "required": ["query"],
            },
            {
                "name": "fetch_url",
                "description": "Fetch and extract readable content from a URL. Returns structured output with title, meta description, and plain text content. SSRF-protected.",
                "parameters": {"url": {"type": "string", "description": "URL to fetch"}},
                "required": ["url"],
            },
            {
                "name": "browse_and_extract",
                "description": "One-shot web research: searches for a query, fetches the top results, and extracts readable content from each page. Best tool for answering questions that need web data.",
                "parameters": {"query": {"type": "string", "description": "Search query to research"}, "max_pages": {"type": "integer", "description": "Number of pages to fetch and extract (default 3, max 5)"}},
                "required": ["query"],
            },
            {
                "name": "detect_search_provider",
                "description": "Check which search providers are configured and return the active provider name and status of all providers.",
                "parameters": {},
                "required": [],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.file_ops",
        "name": "file_ops",
        "description": "Read, write, and list files on the filesystem",
        "tools": [
            {
                "name": "read_file",
                "description": "Read the contents of a text file",
                "parameters": {"path": {"type": "string", "description": "Path to the file"}},
                "required": ["path"],
            },
            {
                "name": "write_file",
                "description": "Write content to a file (creates parent directories if needed)",
                "parameters": {"path": {"type": "string", "description": "Path to write to"}, "content": {"type": "string", "description": "Content to write"}, "idempotency_key": {"type": "string", "description": "Optional idempotency key to prevent duplicate writes on retries"}},
                "required": ["path", "content"],
            },
            {
                "name": "list_directory",
                "description": "List files and directories in a path",
                "parameters": {"path": {"type": "string", "description": "Directory path"}},
                "required": [],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.code_exec",
        "name": "code_exec",
        "description": "Execute Python code in a sandboxed environment",
        "tools": [
            {
                "name": "execute_python",
                "description": "Execute Python code and return the output. Code runs in an isolated sandbox with a 30-second timeout.",
                "parameters": {"code": {"type": "string", "description": "Python code to execute"}},
                "required": ["code"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.repo_exec",
        "name": "repo_exec",
        "description": "Execute scripts and commands from cloned repositories",
        "tools": [
            {
                "name": "run_repo_script",
                "description": "Run a script from a cloned repository. Automatically detects the runtime (Python, Node.js, Bash) and uses the repo's installed dependencies (venv, node_modules).",
                "parameters": {"repo_name": {"type": "string", "description": "Name of the cloned repository"}, "script_path": {"type": "string", "description": "Relative path to the script within the repo (e.g. main.py, src/index.js)"}, "args": {"type": "string", "description": "Command-line arguments to pass to the script"}, "timeout_seconds": {"type": "integer", "description": "Maximum execution time in seconds (default 60, max 300)"}},
                "required": ["repo_name", "script_path"],
            },
            {
                "name": "run_repo_command",
                "description": "Run an arbitrary command within a repo's environment. Use 'subdir' to run from a subdirectory instead of cd. Allowed commands: python, node, npm, npx, cargo, go, bash, pip, pytest, make, maturin, poetry, uv. Dangerous commands are blocked.",
                "parameters": {"repo_name": {"type": "string", "description": "Name of the cloned repository"}, "command": {"type": "string", "description": "Command to run (e.g. 'python -m pytest', 'npm test', 'maturin develop')"}, "subdir": {"type": "string", "description": "Subdirectory within the repo to run the command from (e.g. 'bindings/python'). Defaults to repo root."}, "timeout_seconds": {"type": "integer", "description": "Maximum execution time in seconds (default 60, max 300)"}},
                "required": ["repo_name", "command"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.github_repos",
        "name": "github_repos",
        "description": "Clone GitHub repositories and install their dependencies",
        "tools": [
            {
                "name": "clone_repo",
                "description": "Clone a GitHub/GitLab/Bitbucket repository. Uses shallow clone (--depth 1) for speed. Repos are stored in ~/.neuralclaw/workspace/repos/.",
                "parameters": {"url": {"type": "string", "description": "HTTPS URL of the git repository (e.g. https://github.com/owner/repo)"}, "branch": {"type": "string", "description": "Branch to clone (default: repo default branch)"}},
                "required": ["url"],
            },
            {
                "name": "install_repo_deps",
                "description": "Install dependencies for a cloned repository. Automatically detects requirements.txt, package.json, Cargo.toml, go.mod and installs in isolated environments.",
                "parameters": {"repo_name": {"type": "string", "description": "Name of the cloned repository (from clone_repo or list_repos)"}},
                "required": ["repo_name"],
            },
            {
                "name": "list_repos",
                "description": "List all cloned repositories with their dependency status",
                "parameters": {},
                "required": [],
            },
            {
                "name": "remove_repo",
                "description": "Remove a cloned repository and all its files",
                "parameters": {"repo_name": {"type": "string", "description": "Name of the repository to remove"}},
                "required": ["repo_name"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.github_ops",
        "name": "github_ops",
        "description": "Inspect GitHub issues, pull requests, CI status, and publish comments",
        "tools": [
            {
                "name": "github_list_pull_requests",
                "description": "List pull requests in a repository with author, state, branch info, and draft status.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "state": {"type": "string", "description": "Pull request state", "enum": ["open", "closed", "all"]},
                    "limit": {"type": "integer", "description": "Maximum number of pull requests to return"},
                },
                "required": ["repo"],
            },
            {
                "name": "github_get_pull_request",
                "description": "Get full pull request details including review summary, labels, mergeability, and CI status.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "number": {"type": "integer", "description": "Pull request number"},
                },
                "required": ["repo", "number"],
            },
            {
                "name": "github_list_issues",
                "description": "List issues in a repository with assignee, labels, and timestamps.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "state": {"type": "string", "description": "Issue state", "enum": ["open", "closed", "all"]},
                    "limit": {"type": "integer", "description": "Maximum number of issues to return"},
                },
                "required": ["repo"],
            },
            {
                "name": "github_get_issue",
                "description": "Get issue details plus the latest comments.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "number": {"type": "integer", "description": "Issue number"},
                },
                "required": ["repo", "number"],
            },
            {
                "name": "github_get_ci_status",
                "description": "Get commit and check-run status for a ref, branch, or SHA.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "ref": {"type": "string", "description": "Commit SHA, branch, or PR head ref"},
                },
                "required": ["repo", "ref"],
            },
            {
                "name": "github_comment_issue",
                "description": "Post a comment on a GitHub issue or pull request conversation.",
                "parameters": {
                    "repo": {"type": "string", "description": "Repository in owner/name form"},
                    "number": {"type": "integer", "description": "Issue or pull request number"},
                    "body": {"type": "string", "description": "Comment body"},
                },
                "required": ["repo", "number", "body"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.api_client",
        "name": "api_client",
        "description": "Make authenticated HTTP API requests",
        "tools": [
            {
                "name": "api_request",
                "description": "Make an authenticated HTTP request to an API. Supports GET, POST, PUT, DELETE, PATCH. Use api_name to auto-inject saved credentials.",
                "parameters": {"method": {"type": "string", "description": "HTTP method (GET, POST, PUT, DELETE, PATCH)"}, "url": {"type": "string", "description": "Full URL or relative path (if api_name is provided, relative paths use its base_url)"}, "headers": {"type": "object", "description": "Custom request headers as key-value pairs"}, "body": {"type": "string", "description": "Request body (JSON string for POST/PUT/PATCH)"}, "query_params": {"type": "object", "description": "URL query parameters as key-value pairs"}, "api_name": {"type": "string", "description": "Name of a saved API config (from save_api_config) for auto-authentication"}, "timeout_seconds": {"type": "integer", "description": "Request timeout in seconds (default 30, max 60)"}},
                "required": ["method", "url"],
            },
            {
                "name": "save_api_config",
                "description": "Save an API configuration for reuse. The API key is stored securely in the OS keychain.",
                "parameters": {"name": {"type": "string", "description": "Unique name for this API (e.g. 'openweather', 'github')"}, "base_url": {"type": "string", "description": "Base URL for the API (e.g. 'https://api.openweathermap.org/data/2.5')"}, "auth_type": {"type": "string", "description": "Authentication type: bearer, api_key_header, api_key_query, or basic", "enum": ["bearer", "api_key_header", "api_key_query", "basic"]}, "auth_key": {"type": "string", "description": "The API key or token value"}, "auth_header_name": {"type": "string", "description": "Header name for api_key_header auth type (default: X-API-Key)"}, "auth_query_param": {"type": "string", "description": "Query param name for api_key_query auth type (default: api_key)"}},
                "required": ["name", "base_url", "auth_type", "auth_key"],
            },
            {
                "name": "list_api_configs",
                "description": "List all saved API configurations (keys are never shown)",
                "parameters": {},
                "required": [],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.app_builder",
        "name": "app_builder",
        "description": "Provision app workspaces under the approved apps root",
        "tools": [
            {
                "name": "build_app",
                "description": "Create a new project in the approved apps workspace root and return its exact path so follow-up file writes do not guess locations.",
                "parameters": {"project_name": {"type": "string", "description": "Human-readable project name. This becomes a safe folder slug."}, "template": {"type": "string", "description": "Starter scaffold to create.", "enum": ["generic", "node", "python", "web"]}, "description": {"type": "string", "description": "Short project summary to place into starter files."}, "create_readme": {"type": "boolean", "description": "Whether to create a starter README.md file."}},
                "required": ["project_name"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.database_bi",
        "name": "database_bi",
        "description": "Connect to databases (SQLite, PostgreSQL, MySQL, MongoDB, ClickHouse), run natural-language queries, generate charts, and produce business intelligence insights \u2014 all locally.",
        "tools": [
            {
                "name": "db_connect",
                "description": "Register a named database connection. Supports SQLite, PostgreSQL, MySQL, MongoDB, and ClickHouse.",
                "parameters": {"name": {"type": "string", "description": "Friendly name for this connection (e.g. 'sales_db')"}, "driver": {"type": "string", "description": "Database driver: sqlite, postgres, mysql, mongodb, or clickhouse"}, "dsn": {"type": "string", "description": "Connection string or file path. SQLite: ~/data/sales.db, PostgreSQL: postgresql://user:pass@host:5432/db, MySQL: mysql://user:pass@host/db, MongoDB: mongodb://host:27017/db, ClickHouse: http://host:8123"}, "schema": {"type": "string", "description": "Default schema (PostgreSQL only, defaults to 'public')"}, "read_only": {"type": "boolean", "description": "Block write operations (default: true)"}},
                "required": ["name", "driver", "dsn"],
            },
            {
                "name": "db_disconnect",
                "description": "Remove a saved database connection.",
                "parameters": {"name": {"type": "string", "description": "Connection name to disconnect"}},
                "required": ["name"],
            },
            {
                "name": "db_list_connections",
                "description": "Show all active database connections with status.",
                "parameters": {},
                "required": [],
            },
            {
                "name": "db_list_tables",
                "description": "List all tables or collections in a connected database with row counts.",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}},
                "required": ["connection"],
            },
            {
                "name": "db_describe_table",
                "description": "Show column names, types, and sample rows for a specific table.",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}, "table": {"type": "string", "description": "Table or collection name"}},
                "required": ["connection", "table"],
            },
            {
                "name": "db_query",
                "description": "Execute a raw SQL query and return results. For MongoDB, pass a JSON object with keys: collection, filter, projection, sort, limit.",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}, "query": {"type": "string", "description": "SQL query or MongoDB JSON filter"}},
                "required": ["connection", "query"],
            },
            {
                "name": "db_natural_query",
                "description": "Ask a natural-language question about your database. Automatically generates SQL, executes it, and explains the results. Example: 'What were total sales by region last quarter?'",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}, "question": {"type": "string", "description": "Natural-language question about your data"}},
                "required": ["connection", "question"],
            },
            {
                "name": "db_chart",
                "description": "Execute a query (SQL or natural language) and generate a chart. Supports bar, line, pie, scatter, and heatmap charts.",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}, "query": {"type": "string", "description": "SQL query or natural-language question"}, "chart_type": {"type": "string", "description": "Chart type: bar, line, pie, scatter, or heatmap"}, "title": {"type": "string", "description": "Chart title"}, "x_column": {"type": "string", "description": "Column for X axis (auto-detected if empty)"}, "y_column": {"type": "string", "description": "Column for Y axis (auto-detected if empty)"}, "group_column": {"type": "string", "description": "Column for grouping / heatmap Y axis"}},
                "required": ["connection", "query"],
            },
            {
                "name": "db_explain_data",
                "description": "Run a natural-language query and return only the business analysis \u2014 key trends, outliers, and actionable insights.",
                "parameters": {"connection": {"type": "string", "description": "Name of the database connection"}, "question": {"type": "string", "description": "Business question about your data"}},
                "required": ["connection", "question"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.scheduler",
        "name": "scheduler",
        "description": "Cron-based task scheduling and webhook ingestion for automated agent actions",
        "tools": [
            {
                "name": "schedule_create",
                "description": "Create a cron-based scheduled task. The task will fire automatically on the cron schedule and dispatch the action via the agent runtime.",
                "parameters": {"name": {"type": "string", "description": "Unique name for the scheduled task"}, "cron_expression": {"type": "string", "description": "Standard 5-field cron expression: minute hour day_of_month month day_of_week. Examples: \"0 9 * * 1-5\" (weekdays 9am), \"*/15 * * * *\" (every 15 min), \"0 0 1 * *\" (first of month midnight)"}, "action_type": {"type": "string", "description": "Type of action to execute when the schedule fires", "enum": ["workflow", "message", "skill_call"]}, "action_payload": {"type": "string", "description": "JSON string with action details. For workflow: {\"workflow\": \"name\"}. For message: {\"text\": \"...\"}. For skill_call: {\"skill\": \"name\", \"tool\": \"name\", \"args\": {}}"}, "enabled": {"type": "boolean", "description": "Whether the schedule starts enabled (default true)"}},
                "required": ["name", "cron_expression", "action_type", "action_payload"],
            },
            {
                "name": "schedule_list",
                "description": "List all scheduled tasks with their next run time and status",
                "parameters": {},
                "required": [],
            },
            {
                "name": "schedule_remove",
                "description": "Remove a scheduled task by name",
                "parameters": {"name": {"type": "string", "description": "Name of the scheduled task to remove"}},
                "required": ["name"],
            },
            {
                "name": "schedule_pause",
                "description": "Pause a scheduled task so it will not fire until resumed",
                "parameters": {"name": {"type": "string", "description": "Name of the scheduled task to pause"}},
                "required": ["name"],
            },
            {
                "name": "schedule_resume",
                "description": "Resume a paused scheduled task and recompute its next run time",
                "parameters": {"name": {"type": "string", "description": "Name of the scheduled task to resume"}},
                "required": ["name"],
            },
            {
                "name": "webhook_register",
                "description": "Register a webhook endpoint that dispatches an action when an HTTP request is received at the given path. Supports optional HMAC-SHA256 signature verification.",
                "parameters": {"name": {"type": "string", "description": "Unique name for the webhook handler"}, "path": {"type": "string", "description": "URL path to listen on, e.g. \"/hooks/stripe\" or \"/hooks/github\""}, "action_type": {"type": "string", "description": "Type of action to execute when the webhook fires", "enum": ["workflow", "message", "skill_call"]}, "action_payload_template": {"type": "string", "description": "JSON template for the action payload. Use {{body}} as a placeholder that will be replaced with the raw request body. Example: {\"text\": \"Webhook received: {{body}}\"}"}, "secret": {"type": "string", "description": "Optional HMAC-SHA256 secret for verifying inbound requests. The sender must include an X-Signature-256 header with sha256=<hex-digest>."}},
                "required": ["name", "path", "action_type", "action_payload_template"],
            },
            {
                "name": "webhook_list",
                "description": "List all registered webhook endpoints",
                "parameters": {},
                "required": [],
            },
            {
                "name": "webhook_remove",
                "description": "Remove a registered webhook endpoint by name",
                "parameters": {"name": {"type": "string", "description": "Name of the webhook handler to remove"}},
                "required": ["name"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.pip_install",
        "name": "pip_install",
        "description": "Install Python packages via pip so the agent can use new libraries",
        "tools": [
            {
                "name": "pip_install",
                "description": "Install Python packages via pip. Use this when the user asks you to install a package, or when you need a library that isn't available. Example: pip_install(packages='pyautogui pillow')",
                "parameters": {"packages": {"type": "string", "description": "Space or comma separated package names (e.g. 'pyautogui pillow pandas')"}, "upgrade": {"type": "boolean", "description": "Upgrade packages to latest version"}},
                "required": ["packages"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.tts",
        "name": "tts",
        "description": "Synthesize speech and optionally play it to supported channels.",
        "tools": [
            {
                "name": "speak",
                "description": "Convert text into an audio file.",
                "parameters": {"text": {"type": "string", "description": "Text to synthesize."}, "voice": {"type": "string", "description": "Optional voice preset."}, "speed": {"type": "number", "description": "Speech speed multiplier."}, "output_format": {"type": "string", "description": "Output audio format.", "enum": ["mp3", "wav", "ogg"]}},
                "required": ["text"],
            },
            {
                "name": "list_voices",
                "description": "List available voices for a TTS backend.",
                "parameters": {"provider": {"type": "string", "description": "Optional TTS provider override."}},
                "required": [],
            },
            {
                "name": "speak_and_play",
                "description": "Synthesize speech and play it to a supported channel adapter.",
                "parameters": {"text": {"type": "string", "description": "Text to synthesize."}, "channel_id": {"type": "string", "description": "Target channel id."}, "platform": {"type": "string", "description": "Playback platform."}},
                "required": ["text", "channel_id"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.google_workspace",
        "name": "google_workspace",
        "description": "Access Gmail, Calendar, Drive, Docs, Sheets, and Meet.",
        "tools": [
            {
                "name": "gmail_search",
                "description": "Search Gmail with a query string.",
                "parameters": {"query": {"type": "string", "description": "Gmail search query"}, "max_results": {"type": "integer", "description": "Maximum messages to return"}},
                "required": ["query"],
            },
            {
                "name": "gmail_send",
                "description": "Send an email via Gmail.",
                "parameters": {"to": {"type": "string", "description": "Recipient email"}, "subject": {"type": "string", "description": "Subject"}, "body": {"type": "string", "description": "Email body"}},
                "required": ["to", "subject", "body"],
            },
            {
                "name": "gmail_get",
                "description": "Fetch a Gmail message by id.",
                "parameters": {"message_id": {"type": "string", "description": "Gmail message id"}},
                "required": ["message_id"],
            },
            {
                "name": "gmail_label",
                "description": "Apply or remove labels on a Gmail message.",
                "parameters": {"message_id": {"type": "string", "description": "Gmail message id"}, "add_labels": {"type": "array", "description": "Labels to add", "items": {"type": "string"}}, "remove_labels": {"type": "array", "description": "Labels to remove", "items": {"type": "string"}}},
                "required": ["message_id"],
            },
            {
                "name": "gmail_draft",
                "description": "Create a Gmail draft.",
                "parameters": {"to": {"type": "string", "description": "Recipient email"}, "subject": {"type": "string", "description": "Subject"}, "body": {"type": "string", "description": "Draft body"}},
                "required": ["to", "subject", "body"],
            },
            {
                "name": "gcal_list_events",
                "description": "List Google Calendar events.",
                "parameters": {"time_min": {"type": "string", "description": "Optional ISO start time"}, "time_max": {"type": "string", "description": "Optional ISO end time"}, "calendar_id": {"type": "string", "description": "Optional calendar id"}},
                "required": [],
            },
            {
                "name": "gcal_create_event",
                "description": "Create a Google Calendar event.",
                "parameters": {"summary": {"type": "string", "description": "Event summary"}, "start_time": {"type": "string", "description": "ISO start time"}, "end_time": {"type": "string", "description": "ISO end time"}, "calendar_id": {"type": "string", "description": "Optional calendar id"}},
                "required": ["summary", "start_time", "end_time"],
            },
            {
                "name": "gcal_update_event",
                "description": "Update a Google Calendar event.",
                "parameters": {"event_id": {"type": "string", "description": "Event id"}, "updates": {"type": "object", "description": "Fields to update"}, "calendar_id": {"type": "string", "description": "Optional calendar id"}},
                "required": ["event_id", "updates"],
            },
            {
                "name": "gcal_delete_event",
                "description": "Delete a Google Calendar event.",
                "parameters": {"event_id": {"type": "string", "description": "Event id"}, "calendar_id": {"type": "string", "description": "Optional calendar id"}},
                "required": ["event_id"],
            },
            {
                "name": "gdrive_search",
                "description": "Search Google Drive files.",
                "parameters": {"query": {"type": "string", "description": "Drive search query"}, "max_results": {"type": "integer", "description": "Maximum files to return"}},
                "required": ["query"],
            },
            {
                "name": "gdrive_read",
                "description": "Read a Google Drive file.",
                "parameters": {"file_id": {"type": "string", "description": "Drive file id"}},
                "required": ["file_id"],
            },
            {
                "name": "gdrive_upload",
                "description": "Upload a file to Google Drive.",
                "parameters": {"file_path": {"type": "string", "description": "Local file path"}, "name": {"type": "string", "description": "Optional uploaded name"}, "mime_type": {"type": "string", "description": "Upload mime type"}},
                "required": ["file_path"],
            },
            {
                "name": "gdocs_read",
                "description": "Read a Google Doc.",
                "parameters": {"document_id": {"type": "string", "description": "Document id"}},
                "required": ["document_id"],
            },
            {
                "name": "gdocs_append",
                "description": "Append text to a Google Doc.",
                "parameters": {"document_id": {"type": "string", "description": "Document id"}, "text": {"type": "string", "description": "Text to append"}},
                "required": ["document_id", "text"],
            },
            {
                "name": "gsheets_read",
                "description": "Read values from a Google Sheet range.",
                "parameters": {"spreadsheet_id": {"type": "string", "description": "Spreadsheet id"}, "range_name": {"type": "string", "description": "A1 range"}},
                "required": ["spreadsheet_id", "range_name"],
            },
            {
                "name": "gsheets_write",
                "description": "Write values to a Google Sheet range.",
                "parameters": {"spreadsheet_id": {"type": "string", "description": "Spreadsheet id"}, "range_name": {"type": "string", "description": "A1 range"}, "values": {"type": "array", "description": "Two-dimensional sheet values", "items": {"type": "array"}}},
                "required": ["spreadsheet_id", "range_name", "values"],
            },
            {
                "name": "gmeet_create",
                "description": "Create a Meet-backed calendar event.",
                "parameters": {"summary": {"type": "string", "description": "Meeting summary"}},
                "required": [],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.microsoft365",
        "name": "microsoft365",
        "description": "Access Outlook, Teams, OneDrive, SharePoint, and Microsoft Calendar.",
        "tools": [
            {
                "name": "outlook_search",
                "description": "Search Outlook mail.",
                "parameters": {"query": {"type": "string", "description": "Search query"}, "max_results": {"type": "integer", "description": "Maximum messages"}},
                "required": ["query"],
            },
            {
                "name": "outlook_send",
                "description": "Send Outlook email.",
                "parameters": {"to": {"type": "string", "description": "Recipient email"}, "subject": {"type": "string", "description": "Subject"}, "body": {"type": "string", "description": "Email body"}},
                "required": ["to", "subject", "body"],
            },
            {
                "name": "outlook_get",
                "description": "Fetch Outlook email by id.",
                "parameters": {"message_id": {"type": "string", "description": "Outlook message id"}},
                "required": ["message_id"],
            },
            {
                "name": "ms_cal_list",
                "description": "List Microsoft calendar events.",
                "parameters": {"start_time": {"type": "string", "description": "Optional ISO start time"}, "end_time": {"type": "string", "description": "Optional ISO end time"}},
                "required": [],
            },
            {
                "name": "ms_cal_create",
                "description": "Create Microsoft calendar event.",
                "parameters": {"subject": {"type": "string", "description": "Event subject"}, "start_time": {"type": "string", "description": "ISO start time"}, "end_time": {"type": "string", "description": "ISO end time"}},
                "required": ["subject", "start_time", "end_time"],
            },
            {
                "name": "ms_cal_delete",
                "description": "Delete Microsoft calendar event.",
                "parameters": {"event_id": {"type": "string", "description": "Event id"}},
                "required": ["event_id"],
            },
            {
                "name": "teams_send",
                "description": "Send a Teams chat message.",
                "parameters": {"chat_or_channel_id": {"type": "string", "description": "Teams chat or channel id"}, "text": {"type": "string", "description": "Message body"}},
                "required": ["chat_or_channel_id", "text"],
            },
            {
                "name": "teams_list_channels",
                "description": "List channels for a Team.",
                "parameters": {"team_id": {"type": "string", "description": "Team id"}},
                "required": ["team_id"],
            },
            {
                "name": "onedrive_search",
                "description": "Search OneDrive.",
                "parameters": {"query": {"type": "string", "description": "Search query"}, "max_results": {"type": "integer", "description": "Maximum files"}},
                "required": ["query"],
            },
            {
                "name": "onedrive_read",
                "description": "Read a OneDrive item.",
                "parameters": {"item_id": {"type": "string", "description": "Drive item id"}},
                "required": ["item_id"],
            },
            {
                "name": "onedrive_upload",
                "description": "Upload a file to OneDrive.",
                "parameters": {"file_path": {"type": "string", "description": "Local file path"}, "remote_name": {"type": "string", "description": "Optional remote filename"}},
                "required": ["file_path"],
            },
            {
                "name": "sharepoint_search",
                "description": "Search SharePoint.",
                "parameters": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
            {
                "name": "sharepoint_read",
                "description": "Read a SharePoint resource path.",
                "parameters": {"item_path": {"type": "string", "description": "Graph API item path"}},
                "required": ["item_path"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.knowledge_base",
        "name": "knowledge_base",
        "description": "Ingest, search, and manage documents in the RAG knowledge base",
        "tools": [
            {
                "name": "kb_ingest",
                "description": "Ingest a document file (txt, md, html, csv, pdf, json) into the knowledge base",
                "parameters": {"file_path": {"type": "string", "description": "Path to the document file to ingest"}},
                "required": ["file_path"],
            },
            {
                "name": "kb_ingest_text",
                "description": "Ingest raw text content into the knowledge base",
                "parameters": {"text": {"type": "string", "description": "Text content to ingest"}, "title": {"type": "string", "description": "Optional title for the document"}, "source": {"type": "string", "description": "Optional source identifier"}},
                "required": ["text"],
            },
            {
                "name": "kb_search",
                "description": "Semantic search across all knowledge base documents",
                "parameters": {"query": {"type": "string", "description": "Search query"}, "top_k": {"type": "integer", "description": "Maximum number of results to return"}},
                "required": ["query"],
            },
            {
                "name": "kb_list",
                "description": "List all documents in the knowledge base",
                "parameters": {},
                "required": [],
            },
            {
                "name": "kb_delete",
                "description": "Delete a document and all its chunks from the knowledge base",
                "parameters": {"doc_id": {"type": "string", "description": "Document ID to delete"}},
                "required": ["doc_id"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.workflow_skill",
        "name": "workflow",
        "description": "Create and manage DAG-based multi-step task pipelines with parallel execution and pause/resume",
        "tools": [
            {
                "name": "create_workflow",
                "description": "Create a new workflow pipeline. Each step has: id, name, action (tool name or prompt), action_type ('tool' or 'prompt'), action_params (dict), depends_on (list of step IDs), condition (optional expression). Use {step_id} in action_params to reference previous results.",
                "parameters": {"name": {"type": "string", "description": "Workflow name"}, "steps_json": {"type": "string", "description": "JSON array of step objects, e.g. [{\"id\":\"s1\",\"name\":\"search\",\"action\":\"web_search\",\"action_params\":{\"query\":\"test\"}}]"}, "description": {"type": "string", "description": "Optional workflow description"}, "variables_json": {"type": "string", "description": "Optional JSON object of initial workflow variables"}},
                "required": ["name", "steps_json"],
            },
            {
                "name": "run_workflow",
                "description": "Start executing a workflow. Steps run in parallel where dependencies allow.",
                "parameters": {"workflow_id": {"type": "string", "description": "Workflow ID to execute"}},
                "required": ["workflow_id"],
            },
            {
                "name": "pause_workflow",
                "description": "Pause a running workflow (human-in-the-loop gate)",
                "parameters": {"workflow_id": {"type": "string", "description": "Workflow ID to pause"}},
                "required": ["workflow_id"],
            },
            {
                "name": "resume_workflow",
                "description": "Resume a paused workflow",
                "parameters": {"workflow_id": {"type": "string", "description": "Workflow ID to resume"}},
                "required": ["workflow_id"],
            },
            {
                "name": "workflow_status",
                "description": "Get detailed status of a workflow including all step states",
                "parameters": {"workflow_id": {"type": "string", "description": "Workflow ID"}},
                "required": ["workflow_id"],
            },
            {
                "name": "list_workflows",
                "description": "List all workflows with their status",
                "parameters": {},
                "required": [],
            },
            {
                "name": "delete_workflow",
                "description": "Delete a workflow and its run history",
                "parameters": {"workflow_id": {"type": "string", "description": "Workflow ID to delete"}},
                "required": ["workflow_id"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.calendar_skill",
        "name": "calendar",
        "description": "Manage a local calendar \u2014 create, list, and delete events",
        "tools": [
            {
                "name": "create_event",
                "description": "Create a new calendar event",
                "parameters": {"title": {"type": "string", "description": "Event title"}, "start_time": {"type": "string", "description": "Start time (ISO format, e.g. 2026-02-23T14:00)"}, "end_time": {"type": "string", "description": "End time (ISO format)"}, "description": {"type": "string", "description": "Event description"}, "location": {"type": "string", "description": "Event location"}, "idempotency_key": {"type": "string", "description": "Optional idempotency key to prevent duplicates on retries"}},
                "required": ["title", "start_time"],
            },
            {
                "name": "list_events",
                "description": "List calendar events, optionally filtered by date",
                "parameters": {"date": {"type": "string", "description": "Date to filter by (YYYY-MM-DD format)"}},
                "required": [],
            },
            {
                "name": "delete_event",
                "description": "Delete a calendar event by its ID",
                "parameters": {"event_id": {"type": "string", "description": "Event ID to delete"}, "idempotency_key": {"type": "string", "description": "Optional idempotency key to prevent duplicates on retries"}},
                "required": ["event_id"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.clipboard_intel",
        "name": "clipboard_intel",
        "description": "Cross-platform clipboard monitoring, entity extraction, and contextual action suggestions. Maintains a history ring buffer of recent clipboard entries.",
        "tools": [
            {
                "name": "clipboard_watch",
                "description": "Start or stop clipboard monitoring. When active, polls the system clipboard every 2 seconds and records changes in a history ring buffer (last 50 entries).",
                "parameters": {"action": {"type": "string", "description": "Action to perform: 'start', 'stop', or 'status'", "enum": ["start", "stop", "status"]}},
                "required": [],
            },
            {
                "name": "clipboard_history",
                "description": "Return recent clipboard entries from the ring buffer. Each entry includes copied text, UTC timestamp, detected entities, and content type classification.",
                "parameters": {"limit": {"type": "integer", "description": "Number of entries to return (default 20, max 50)"}},
                "required": [],
            },
            {
                "name": "clipboard_analyze",
                "description": "Analyze the current clipboard content. Detects content type (URL, email, code, JSON, IP, file path, plain text) and extracts all structured entities.",
                "parameters": {},
                "required": [],
            },
            {
                "name": "clipboard_smart_paste",
                "description": "Read the clipboard and return its content with suggested contextual actions based on detected content type and extracted entities.",
                "parameters": {},
                "required": [],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.kpi_monitor",
        "name": "kpi_monitor",
        "description": "Create and manage KPI monitoring agents that watch metrics and alert when thresholds are breached",
        "tools": [
            {
                "name": "kpi_create_monitor",
                "description": "Create a named KPI monitor that periodically checks a metric and alerts when thresholds are breached. Supported check types: http_status, http_json_field, database_query, file_metric, custom_python.",
                "parameters": {"name": {"type": "string", "description": "Unique name for this KPI monitor"}, "description": {"type": "string", "description": "Human-readable description of what this monitor tracks"}, "check_type": {"type": "string", "description": "Type of check to perform", "enum": ["http_status", "http_json_field", "database_query", "file_metric", "custom_python"]}, "target": {"type": "string", "description": "The target to check: a URL for http_status/http_json_field, a SQL query for database_query, a file path for file_metric, or a Python snippet for custom_python"}, "field_path": {"type": "string", "description": "Dot-separated path to extract a value from JSON response or JSON file (e.g. 'data.metrics.cpu_usage'). Used by http_json_field and file_metric check types."}, "threshold_min": {"type": "number", "description": "Minimum acceptable value. Readings below this are critical."}, "threshold_max": {"type": "number", "description": "Maximum acceptable value. Readings above this are critical."}, "check_interval_seconds": {"type": "integer", "description": "How often to run the check in seconds (default 300, min 10)"}, "alert_message_template": {"type": "string", "description": "Template for alert messages. Available placeholders: {name}, {status}, {value}."}},
                "required": ["name", "check_type", "target"],
            },
            {
                "name": "kpi_list_monitors",
                "description": "List all active KPI monitors with their configuration and last readings.",
                "parameters": {},
                "required": [],
            },
            {
                "name": "kpi_remove_monitor",
                "description": "Remove a KPI monitor by name and stop its background task.",
                "parameters": {"name": {"type": "string", "description": "Name of the monitor to remove"}},
                "required": ["name"],
            },
            {
                "name": "kpi_check_now",
                "description": "Manually trigger an immediate check for a specific monitor (by name) or all monitors (if name is empty).",
                "parameters": {"name": {"type": "string", "description": "Name of the monitor to check. Leave empty to check all."}},
                "required": [],
            },
            {
                "name": "kpi_history",
                "description": "Return the last N readings for a named KPI monitor.",
                "parameters": {"name": {"type": "string", "description": "Name of the monitor"}, "limit": {"type": "integer", "description": "Maximum number of readings to return (default 20, max 100)"}},
                "required": ["name"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.context_aware",
        "name": "context_aware",
        "description": "Context-aware suggestions based on the user's active desktop environment. Detects the foreground application and recommends relevant NeuralClaw actions.",
        "tools": [
            {
                "name": "context_detect",
                "description": "Detect the currently active window/application on the user's desktop. Returns the app name, window title, and a list of suggested NeuralClaw actions relevant to the detected context. Cross-platform: Windows, macOS, Linux.",
                "parameters": {},
                "required": [],
            },
            {
                "name": "context_suggest",
                "description": "Given an application context (app name, window title, and optional clipboard content), suggest relevant NeuralClaw actions. Uses a rule-based mapping with optional LLM enhancement for richer suggestions.",
                "parameters": {"app_name": {"type": "string", "description": "Name of the active application (e.g. 'chrome', 'vscode', 'excel')"}, "window_title": {"type": "string", "description": "Title of the active window"}, "clipboard_content": {"type": "string", "description": "Current clipboard text content for additional context-aware suggestions"}},
                "required": ["app_name"],
            },
            {
                "name": "context_quick_action",
                "description": "Execute a pre-defined contextual quick action by name. Available actions: summarize_page (browser), explain_code (IDE), analyze_data (spreadsheet), draft_reply (email/message), format_text (editor). If an LLM provider is configured, returns the generated result; otherwise returns the prompt template.",
                "parameters": {"action_name": {"type": "string", "description": "Name of the quick action to execute", "enum": ["summarize_page", "explain_code", "analyze_data", "draft_reply", "format_text"]}, "context_text": {"type": "string", "description": "Text content to process (e.g. page content, code snippet, email body). Required for LLM execution; optional if you only need the prompt."}},
                "required": ["action_name"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.digest",
        "name": "digest",
        "description": "Summarise and digest information into structured briefings",
        "tools": [
            {
                "name": "digest_create",
                "description": "Create a digest or briefing from provided text content. Supports bullet, paragraph, and executive summary formats.",
                "parameters": {"title": {"type": "string", "description": "Title for the digest"}, "content": {"type": "string", "description": "Raw text content to summarise"}, "format": {"type": "string", "description": "Output format: bullet, paragraph, or executive", "enum": ["bullet", "paragraph", "executive"]}, "max_length": {"type": "integer", "description": "Maximum length of the summary in characters (default 500)"}},
                "required": ["title", "content"],
            },
            {
                "name": "digest_morning_briefing",
                "description": "Generate a morning briefing combining recent episodic memory highlights, pending tasks, calendar events, and KPI alerts into a structured overview.",
                "parameters": {},
                "required": [],
            },
            {
                "name": "digest_summarize_thread",
                "description": "Summarise a conversation thread into key points, decisions, and action items. Provide messages as a JSON array of {author, text, timestamp} objects.",
                "parameters": {"messages": {"type": "string", "description": "JSON array of message objects, each with keys: author (string), text (string), timestamp (string, optional)"}, "focus": {"type": "string", "description": "Optional topic to focus the summary on"}},
                "required": ["messages"],
            },
            {
                "name": "digest_compare",
                "description": "Compare two datasets or reports and surface differences, trends, and actionable insights.",
                "parameters": {"data_a": {"type": "string", "description": "First dataset or report (text or JSON)"}, "data_b": {"type": "string", "description": "Second dataset or report (text or JSON)"}, "context": {"type": "string", "description": "Description of what is being compared"}},
                "required": ["data_a", "data_b"],
            },
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.framework_intel",
        "name": "framework_intel",
        "description": "NeuralClaw self-knowledge: explore workspace layout, list skills, get skill templates, see active agents, and claim/release directories for multi-agent coordination.",
        "tools": [
            {"name": "list_workspace_structure", "description": "Show the NeuralClaw directory layout with AGENTS.md orientation and active workspace claims.", "parameters": {"include_hidden": {"type": "boolean", "description": "Include hidden files/dirs (default false)"}}, "required": []},
            {"name": "list_available_skills", "description": "List all registered skills with name, description, and tool count. Does NOT trigger lazy imports.", "parameters": {"source_filter": {"type": "string", "description": "Filter: all | builtin | user", "enum": ["all", "builtin", "user"]}}, "required": []},
            {"name": "get_skill_template", "description": "Get a ready-to-paste Python skill template.", "parameters": {"skill_type": {"type": "string", "description": "basic | api | filesystem | stateful", "enum": ["basic", "api", "filesystem", "stateful"]}}, "required": []},
            {"name": "get_active_agents", "description": "List all running agents with status, capabilities, and workspace claims.", "parameters": {}, "required": []},
            {"name": "claim_workspace_dir", "description": "Claim a directory for exclusive use. Returns success=False if already claimed.", "parameters": {"path": {"type": "string", "description": "Directory path"}, "purpose": {"type": "string", "description": "Reason"}, "ttl_seconds": {"type": "number", "description": "Auto-expire seconds (0=never)"}}, "required": ["path"]},
            {"name": "release_workspace_dir", "description": "Release a directory claim made by this agent.", "parameters": {"path": {"type": "string", "description": "Directory path"}}, "required": ["path"]},
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.project_scaffold",
        "name": "project_scaffold",
        "description": "Create complete project structures with AGENTS.md, README, CI stubs. Templates: python-service, fastapi, cli-tool, data-pipeline, agent-skill.",
        "tools": [
            {"name": "scaffold_project", "description": "Scaffold a new project from template with AGENTS.md and README.", "parameters": {"project_name": {"type": "string", "description": "Project name"}, "template": {"type": "string", "description": "Template type", "enum": ["python-service", "python-lib", "fastapi", "cli-tool", "data-pipeline", "agent-skill", "generic"]}, "description": {"type": "string", "description": "Short description"}, "author": {"type": "string", "description": "Author"}, "claim_directory": {"type": "boolean", "description": "Claim dir before writing"}}, "required": ["project_name"]},
            {"name": "list_projects", "description": "List all scaffolded projects (dirs with AGENTS.md).", "parameters": {}, "required": []},
            {"name": "get_project_info", "description": "Get AGENTS.md and directory listing for a project.", "parameters": {"project_name": {"type": "string", "description": "Project name"}}, "required": ["project_name"]},
            {"name": "add_to_project", "description": "Add a component (dockerfile, ci_github, ci_gitlab, makefile, test) to an existing project.", "parameters": {"project_name": {"type": "string", "description": "Project name"}, "component": {"type": "string", "description": "Component type", "enum": ["dockerfile", "ci_github", "ci_gitlab", "makefile", "test"]}}, "required": ["project_name", "component"]},
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.vision",
        "name": "vision",
        "description": "Analyze images, extract text (OCR), describe screenshots, and compare images using vision-capable LLMs (Anthropic, OpenAI, or local Ollama llava).",
        "tools": [
            {"name": "analyze_image", "description": "Analyze an image from a file path or URL. Ask any question about it.", "parameters": {"source": {"type": "string", "description": "File path or HTTPS URL to the image"}, "prompt": {"type": "string", "description": "What to ask about the image"}}, "required": ["source"]},
            {"name": "extract_text_from_image", "description": "Extract all readable text from an image (OCR-style).", "parameters": {"source": {"type": "string", "description": "File path or HTTPS URL to the image"}}, "required": ["source"]},
            {"name": "describe_screenshot", "description": "Describe a screenshot — UI elements, errors, data, text visible on screen.", "parameters": {"source": {"type": "string", "description": "File path or HTTPS URL to the screenshot"}, "focus": {"type": "string", "description": "Optional focus area e.g. 'the error message'"}}, "required": ["source"]},
            {"name": "compare_images", "description": "Compare two images and describe differences or similarities.", "parameters": {"source_a": {"type": "string", "description": "First image"}, "source_b": {"type": "string", "description": "Second image"}, "prompt": {"type": "string", "description": "Comparison instruction"}}, "required": ["source_a", "source_b"]},
            {"name": "detect_vision_capability", "description": "Check which vision providers are available.", "parameters": {}, "required": []},
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.self_config",
        "name": "self_config",
        "description": "Inspect and modify the agent's own runtime configuration: features, skills, and model roles.",
        "tools": [
            {"name": "list_features", "description": "List all feature toggles and their current state.", "parameters": {}, "required": []},
            {"name": "set_feature", "description": "Enable or disable a feature by name.", "parameters": {"name": {"type": "string", "description": "Feature name"}, "enabled": {"type": "boolean", "description": "True to enable"}}, "required": ["name", "enabled"]},
            {"name": "list_skills", "description": "List every loaded skill with its tools and whether each tool is currently allowed.", "parameters": {}, "required": []},
            {"name": "set_skill_enabled", "description": "Allow or disallow a specific tool by name in the policy allowlist.", "parameters": {"tool_name": {"type": "string", "description": "Tool name"}, "enabled": {"type": "boolean", "description": "True to allow"}}, "required": ["tool_name", "enabled"]},
            {"name": "get_config", "description": "Return a redacted snapshot of the current runtime config.", "parameters": {}, "required": []},
            {"name": "list_available_models", "description": "List all models available at the configured Ollama endpoint plus current role bindings.", "parameters": {}, "required": []},
            {"name": "set_model_role", "description": "Bind a model name to a role (primary, fast, micro, embed).", "parameters": {"role": {"type": "string", "description": "Role", "enum": ["primary", "fast", "micro", "embed"]}, "model": {"type": "string", "description": "Model name"}}, "required": ["role", "model"]},
        ],
    },
    {
        "module": "neuralclaw.skills.builtins.agent_orchestration",
        "name": "agent_orchestration",
        "description": "Create persistent worker definitions, spawn agents, inspect the live roster, and delegate work across manual, auto-route, consensus, or pipeline modes.",
        "tools": [
            {"name": "list_agent_definitions", "description": "List saved agent definitions and show which ones are currently running.", "parameters": {}, "required": []},
            {"name": "create_agent_definition", "description": "Create a persistent worker definition and optionally spawn it immediately.", "parameters": {"name": {"type": "string", "description": "Unique agent name"}, "model": {"type": "string", "description": "Model name"}, "description": {"type": "string", "description": "Human-readable summary"}, "capabilities": {"type": "array", "description": "Capabilities or specialties", "items": {"type": "string"}}, "provider": {"type": "string", "description": "Provider route"}, "base_url": {"type": "string", "description": "Optional base URL override"}, "system_prompt": {"type": "string", "description": "Optional specialist prompt"}, "memory_namespace": {"type": "string", "description": "Optional isolated memory namespace"}, "auto_start": {"type": "boolean", "description": "Auto-start on gateway boot"}, "spawn_now": {"type": "boolean", "description": "Spawn immediately after saving"}, "metadata": {"type": "object", "description": "Optional metadata"}}, "required": ["name", "model"]},
            {"name": "update_agent_definition", "description": "Update an existing agent definition by id or name.", "parameters": {"agent_id": {"type": "string", "description": "Saved agent id"}, "name": {"type": "string", "description": "Existing agent name"}, "new_name": {"type": "string", "description": "Rename the agent"}, "description": {"type": "string", "description": "Updated description"}, "capabilities": {"type": "array", "description": "Updated capability list", "items": {"type": "string"}}, "provider": {"type": "string", "description": "Updated provider"}, "model": {"type": "string", "description": "Updated model"}, "base_url": {"type": "string", "description": "Updated base URL"}, "system_prompt": {"type": "string", "description": "Updated system prompt"}, "memory_namespace": {"type": "string", "description": "Updated memory namespace"}, "auto_start": {"type": "boolean", "description": "Updated auto-start setting"}, "metadata": {"type": "object", "description": "Replacement metadata"}}, "required": []},
            {"name": "spawn_defined_agent", "description": "Spawn a saved worker by id or name.", "parameters": {"agent_id": {"type": "string", "description": "Saved agent id"}, "name": {"type": "string", "description": "Saved agent name"}}, "required": []},
            {"name": "despawn_defined_agent", "description": "Stop a saved worker by id or name.", "parameters": {"agent_id": {"type": "string", "description": "Saved agent id"}, "name": {"type": "string", "description": "Saved agent name"}}, "required": []},
            {"name": "list_running_agents", "description": "List all currently running agents in the live swarm.", "parameters": {}, "required": []},
            {"name": "orchestrate_agent_task", "description": "Delegate work using manual, auto-route, consensus, or pipeline mode. Auto mode chooses a suitable path and can auto-spawn missing saved workers first.", "parameters": {"task": {"type": "string", "description": "Task or question to execute"}, "mode": {"type": "string", "description": "auto, manual, auto-route, pipeline, or consensus", "enum": ["auto", "manual", "auto-route", "pipeline", "consensus"]}, "agent_names": {"type": "array", "description": "Target agent names", "items": {"type": "string"}}, "title": {"type": "string", "description": "Optional durable task title"}, "success_criteria": {"type": "string", "description": "What counts as done"}, "deliverables": {"type": "array", "description": "Expected outputs", "items": {"type": "string"}}, "workspace_path": {"type": "string", "description": "Optional repo or project path"}, "integration_targets": {"type": "array", "description": "Integrations this run should touch", "items": {"type": "string"}}, "execution_mode": {"type": "string", "description": "agent-task, workspace-run, integration-loop, or review-pass"}, "require_approval": {"type": "boolean", "description": "Gate execution for user approval first"}, "approval_note": {"type": "string", "description": "Approval guidance for the inbox"}, "timeout_seconds": {"type": "integer", "description": "Optional timeout override"}, "max_agents": {"type": "integer", "description": "Used for auto-route mode"}, "consensus_strategy": {"type": "string", "description": "Consensus strategy"}, "shared_handoff": {"type": "boolean", "description": "Prefer pipeline handoff when multiple agents are specified"}, "create_shared_task": {"type": "boolean", "description": "Create shared-task memory for manual multi-agent fanout"}, "spawn_missing": {"type": "boolean", "description": "Auto-spawn saved workers before delegation"}}, "required": ["task"]},
        ],
    },
]
