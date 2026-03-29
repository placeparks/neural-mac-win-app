"""
Built-in Skill: App Builder - Provision app workspaces under an approved root.

This gives agents a dedicated workflow for starting new projects without
guessing where they should live. All projects are created under the configured
workspace apps root.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


APPS_DIR = Path.home() / "projects"

SUPPORTED_TEMPLATES = {"generic", "web", "python", "node"}


def set_workspace_config(config: Any) -> None:
    """Configure the apps workspace root from ``WorkspaceConfig``."""
    global APPS_DIR
    if hasattr(config, "apps_dir") and config.apps_dir:
        APPS_DIR = Path(str(config.apps_dir)).expanduser()


def _slugify_project_name(project_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_name.strip().lower())
    return slug.strip("-")


def _resolve_project_dir(project_name: str) -> tuple[str | None, Path | None, dict[str, Any] | None]:
    slug = _slugify_project_name(project_name)
    if not slug:
        return None, None, {"error": "Project name must contain letters or numbers."}

    try:
        root = APPS_DIR.resolve()
        project_dir = (APPS_DIR / slug).resolve()
        if not project_dir.is_relative_to(root):
            return None, None, {"error": "Project path escaped the approved apps workspace root."}
    except (OSError, RuntimeError, ValueError):
        return None, None, {"error": "Failed to resolve the apps workspace root."}

    return slug, project_dir, None


def _shared_gitignore() -> str:
    return "\n".join(
        [
            ".DS_Store",
            "__pycache__/",
            "*.pyc",
            ".pytest_cache/",
            ".venv/",
            "node_modules/",
            "dist/",
            "build/",
            "",
        ]
    )


def _readme(project_name: str, template: str, description: str) -> str:
    summary = description.strip() or f"{project_name} scaffolded by NeuralClaw."
    return (
        f"# {project_name}\n\n"
        f"{summary}\n\n"
        "## Template\n\n"
        f"- `{template}`\n"
    )


def _template_files(project_name: str, template: str, description: str) -> dict[str, str]:
    base = {
        "README.md": _readme(project_name, template, description),
        ".gitignore": _shared_gitignore(),
    }

    if template == "generic":
        return base

    if template == "web":
        return {
            **base,
            "index.html": (
                "<!doctype html>\n"
                "<html lang=\"en\">\n"
                "  <head>\n"
                "    <meta charset=\"utf-8\" />\n"
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                f"    <title>{project_name}</title>\n"
                "    <link rel=\"stylesheet\" href=\"styles.css\" />\n"
                "  </head>\n"
                "  <body>\n"
                "    <main>\n"
                f"      <h1>{project_name}</h1>\n"
                f"      <p>{description.strip() or 'Start building here.'}</p>\n"
                "    </main>\n"
                "    <script src=\"app.js\"></script>\n"
                "  </body>\n"
                "</html>\n"
            ),
            "styles.css": (
                ":root {\n"
                "  color-scheme: light;\n"
                "  font-family: \"Segoe UI\", sans-serif;\n"
                "}\n\n"
                "body {\n"
                "  margin: 0;\n"
                "  min-height: 100vh;\n"
                "  display: grid;\n"
                "  place-items: center;\n"
                "  background: linear-gradient(135deg, #f4f7fb, #dde7f5);\n"
                "  color: #172033;\n"
                "}\n\n"
                "main {\n"
                "  width: min(640px, calc(100vw - 3rem));\n"
                "  padding: 2rem;\n"
                "  background: rgba(255, 255, 255, 0.82);\n"
                "  border-radius: 20px;\n"
                "  box-shadow: 0 24px 60px rgba(23, 32, 51, 0.12);\n"
                "}\n"
            ),
            "app.js": (
                "const heading = document.querySelector('h1');\n"
                "if (heading) {\n"
                "  heading.dataset.ready = 'true';\n"
                "}\n"
            ),
        }

    if template == "python":
        return {
            **base,
            "main.py": (
                "def main() -> None:\n"
                f"    print(\"{project_name} is ready\")\n\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            ),
            "requirements.txt": "",
        }

    return {
        **base,
        "package.json": json.dumps(
            {
                "name": _slugify_project_name(project_name),
                "version": "0.1.0",
                "private": True,
                "type": "module",
                "scripts": {
                    "start": "node src/index.js",
                },
            },
            indent=2,
        )
        + "\n",
        "src/index.js": (
            f"console.log('{project_name} is ready');\n"
        ),
    }


async def build_app(
    project_name: str,
    template: str = "generic",
    description: str = "",
    create_readme: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Create or reuse an app project directory under the approved workspace root.
    """
    normalized_template = template.strip().lower() or "generic"
    if normalized_template not in SUPPORTED_TEMPLATES:
        return {
            "error": (
                f"Unsupported template '{template}'. "
                f"Supported templates: {sorted(SUPPORTED_TEMPLATES)}"
            )
        }

    slug, project_dir, error = _resolve_project_dir(project_name)
    if error:
        return error
    assert slug is not None and project_dir is not None

    APPS_DIR.mkdir(parents=True, exist_ok=True)

    already_existed = project_dir.exists()
    project_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "project_name": project_name,
        "slug": slug,
        "template": normalized_template,
        "description": description.strip(),
        "workspace_root": str(APPS_DIR.resolve()),
    }
    (project_dir / ".neuralclaw-app.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )

    created_files: list[str] = [".neuralclaw-app.json"]
    if not already_existed:
        for relative_path, content in _template_files(project_name, normalized_template, description).items():
            if relative_path == "README.md" and not create_readme:
                continue
            target = project_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            created_files.append(relative_path)

    return {
        "success": True,
        "project_name": project_name,
        "project_slug": slug,
        "template": normalized_template,
        "project_path": str(project_dir),
        "workspace_root": str(APPS_DIR.resolve()),
        "already_existed": already_existed,
        "created_files": created_files,
    }


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="app_builder",
        description="Provision app workspaces under the approved apps root",
        capabilities=[Capability.FILESYSTEM_WRITE, Capability.FILESYSTEM_READ],
        tools=[
            ToolDefinition(
                name="build_app",
                description=(
                    "Create a new project in the approved apps workspace root and return "
                    "its exact path so follow-up file writes do not guess locations."
                ),
                parameters=[
                    ToolParameter(
                        name="project_name",
                        type="string",
                        description="Human-readable project name. This becomes a safe folder slug.",
                    ),
                    ToolParameter(
                        name="template",
                        type="string",
                        description="Starter scaffold to create.",
                        required=False,
                        default="generic",
                        enum=sorted(SUPPORTED_TEMPLATES),
                    ),
                    ToolParameter(
                        name="description",
                        type="string",
                        description="Short project summary to place into starter files.",
                        required=False,
                        default="",
                    ),
                    ToolParameter(
                        name="create_readme",
                        type="boolean",
                        description="Whether to create a starter README.md file.",
                        required=False,
                        default=True,
                    ),
                ],
                handler=build_app,
            ),
        ],
    )
