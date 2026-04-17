"""
Built-in Skill: Project Scaffold — Create complete project structures from scratch.

Extends app_builder with richer templates that include AGENTS.md, proper
subdirectory layout, CI stubs, and workspace coordination for multi-agent safety.

Templates: python-service, python-lib, fastapi, cli-tool, data-pipeline,
           agent-skill, generic
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Module-level state — injected by gateway.initialize()
# ---------------------------------------------------------------------------

_workspace_config: Any = None
_workspace_coordinator: Any = None
_agent_name: str = "unknown"
_apps_dir: Path = Path.home() / "projects"


def set_workspace_config(config: Any) -> None:
    global _workspace_config, _apps_dir
    _workspace_config = config
    if hasattr(config, "apps_dir") and config.apps_dir:
        env = os.environ.get("NEURALCLAW_PROJECTS_DIR")
        _apps_dir = Path(env) if env else Path(str(config.apps_dir)).expanduser()


def set_workspace_coordinator(coordinator: Any) -> None:
    global _workspace_coordinator
    _workspace_coordinator = coordinator


def set_agent_name(name: str) -> None:
    global _agent_name
    _agent_name = name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return slug.strip("-")


def _resolve_dir(project_name: str) -> tuple[str | None, Path | None, dict | None]:
    slug = _slugify(project_name)
    if not slug:
        return None, None, {"error": "Project name must contain letters or numbers."}
    project_dir = _apps_dir / slug
    return slug, project_dir, None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _agents_md(slug: str, description: str, template: str, layout_lines: list[str], run_cmd: str) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    layout = "\n".join(f"- `{l}`" for l in layout_lines)
    return f"""\
# {slug}

{description}

**Template:** `{template}`
**Created by:** `{_agent_name}` at {ts}

## Directory Layout
{layout}

## Run
```
{run_cmd}
```

## How to extend this project
- Add features by editing files in `src/` (or `app/` for FastAPI)
- Run tests: `pytest tests/`
- Use `add_to_project` tool to add Dockerfile, CI, Makefile stubs
- Claim this directory before bulk edits: `claim_workspace_dir("{slug}")`
"""


# ---------------------------------------------------------------------------
# Template factories
# ---------------------------------------------------------------------------

def _scaffold_python_service(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / "src" / pkg / "__init__.py", f'"""{ description }"""\n\n__version__ = "0.1.0"\n')
    _write(project_dir / "src" / pkg / "main.py", f'"""Entry point for {slug}."""\n\ndef run() -> None:\n    print("Hello from {slug}")\n\n\nif __name__ == "__main__":\n    run()\n')
    _write(project_dir / "tests" / "__init__.py", "")
    _write(project_dir / "tests" / f"test_{pkg}.py", f'"""Tests for {slug}."""\nimport pytest\n\n\ndef test_placeholder():\n    assert True\n')
    _write(project_dir / "docs" / "README.md", f"# {slug} Docs\n\nAdd documentation here.\n")
    _write(project_dir / "pyproject.toml", f'[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.backends.legacy:build"\n\n[project]\nname = "{slug}"\nversion = "0.1.0"\ndescription = "{description}"\nauthors = [{{name = "{author}"}}]\nrequires-python = ">=3.11"\n\n[project.scripts]\n{slug} = "{pkg}.main:run"\n')
    _write(project_dir / "Makefile", f".PHONY: install test lint\n\ninstall:\n\tpip install -e .[dev]\n\ntest:\n\tpytest tests/ -v\n\nlint:\n\truff check src/ tests/\n")
    _write(project_dir / "Dockerfile", f'FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -e .\nCMD ["{slug}"]\n')
    return [
        f"src/{pkg}/__init__.py",
        f"src/{pkg}/main.py",
        "tests/",
        "docs/",
        "pyproject.toml",
        "Makefile",
        "Dockerfile",
    ]


def _scaffold_python_lib(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / "src" / pkg / "__init__.py", f'"""{description}\n\nExample usage::\n\n    from {pkg} import ...\n"""\n\n__version__ = "0.1.0"\n__all__: list[str] = []\n')
    _write(project_dir / "src" / pkg / "py.typed", "")
    _write(project_dir / "tests" / "__init__.py", "")
    _write(project_dir / "tests" / f"test_{pkg}.py", f'"""Tests for {slug}."""\nimport pytest\nfrom {pkg} import __version__\n\n\ndef test_version():\n    assert __version__ == "0.1.0"\n')
    _write(project_dir / "pyproject.toml", f'[build-system]\nrequires = ["setuptools>=68", "wheel"]\nbuild-backend = "setuptools.backends.legacy:build"\n\n[project]\nname = "{slug}"\nversion = "0.1.0"\ndescription = "{description}"\nauthors = [{{name = "{author}"}}]\nrequires-python = ">=3.11"\n\n[tool.setuptools.packages.find]\nwhere = ["src"]\n')
    return [f"src/{pkg}/__init__.py", f"src/{pkg}/py.typed", "tests/", "pyproject.toml"]


def _scaffold_fastapi(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / "app" / "__init__.py", "")
    _write(project_dir / "app" / "main.py", f'"""FastAPI application for {slug}."""\nfrom fastapi import FastAPI\n\napp = FastAPI(title="{slug}", description="{description}")\n\n\n@app.get("/health")\nasync def health() -> dict:\n    return {{"status": "ok"}}\n')
    _write(project_dir / "app" / "routers" / "__init__.py", "")
    _write(project_dir / "app" / "routers" / "items.py", 'from fastapi import APIRouter\n\nrouter = APIRouter(prefix="/items", tags=["items"])\n\n\n@router.get("/")\nasync def list_items() -> list:\n    return []\n')
    _write(project_dir / "app" / "models" / "__init__.py", "")
    _write(project_dir / "app" / "models" / "item.py", 'from pydantic import BaseModel\n\n\nclass Item(BaseModel):\n    id: int\n    name: str\n')
    _write(project_dir / "tests" / "__init__.py", "")
    _write(project_dir / "tests" / "test_main.py", 'from fastapi.testclient import TestClient\nfrom app.main import app\n\nclient = TestClient(app)\n\n\ndef test_health():\n    r = client.get("/health")\n    assert r.status_code == 200\n')
    _write(project_dir / "requirements.txt", "fastapi>=0.110\nuvicorn[standard]>=0.27\npydantic>=2\n")
    _write(project_dir / "Dockerfile", f'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n')
    return ["app/main.py", "app/routers/", "app/models/", "tests/", "requirements.txt", "Dockerfile"]


def _scaffold_cli_tool(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / "src" / "cli.py", f'"""Command-line interface for {slug}."""\nimport argparse\n\n\ndef main() -> None:\n    parser = argparse.ArgumentParser(description="{description}")\n    parser.add_argument("--version", action="version", version="0.1.0")\n    args = parser.parse_args()\n    print("Hello from {slug}")\n\n\nif __name__ == "__main__":\n    main()\n')
    _write(project_dir / "setup.py", f'from setuptools import setup, find_packages\n\nsetup(\n    name="{slug}",\n    version="0.1.0",\n    description="{description}",\n    packages=find_packages("src"),\n    package_dir={{"": "src"}},\n    entry_points={{"console_scripts": ["{slug}=cli:main"]}},\n    python_requires=">=3.11",\n)\n')
    _write(project_dir / "tests" / "test_cli.py", "def test_placeholder():\n    assert True\n")
    return ["src/cli.py", "setup.py", "tests/"]


def _scaffold_data_pipeline(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / "src" / "pipeline.py", f'"""Data pipeline for {slug}."""\nfrom pathlib import Path\n\nRAW_DIR = Path(__file__).parent.parent / "data" / "raw"\nPROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"\n\n\ndef run_pipeline() -> None:\n    RAW_DIR.mkdir(parents=True, exist_ok=True)\n    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)\n    print(f"Pipeline ready. Raw: {{RAW_DIR}}, Processed: {{PROCESSED_DIR}}")\n\n\nif __name__ == "__main__":\n    run_pipeline()\n')
    _write(project_dir / "data" / "raw" / ".gitkeep", "")
    _write(project_dir / "data" / "processed" / ".gitkeep", "")
    _write(project_dir / "notebooks" / "exploration.ipynb", '{"cells": [], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}\n')
    _write(project_dir / "requirements.txt", "pandas>=2\nnumpy>=1.26\nnotebook>=7\n")
    return ["src/pipeline.py", "data/raw/", "data/processed/", "notebooks/", "requirements.txt"]


def _scaffold_agent_skill(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    pkg = slug.replace("-", "_")
    _write(project_dir / f"{pkg}.py", f'"""\nNeuralClaw skill: {slug}\n\n{description}\n"""\nfrom __future__ import annotations\n\nfrom neuralclaw.cortex.action.capabilities import Capability\nfrom neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n\n\nasync def do_thing(input: str, **kwargs) -> dict:\n    """Replace with your implementation."""\n    return {{"result": input}}\n\n\ndef get_manifest() -> SkillManifest:\n    return SkillManifest(\n        name="{pkg}",\n        description="{description}",\n        capabilities=[],\n        tools=[\n            ToolDefinition(\n                name="do_thing",\n                description="Do the thing",\n                parameters=[\n                    ToolParameter(name="input", type="string", description="Input", required=True),\n                ],\n                handler=do_thing,\n            )\n        ],\n    )\n')
    _write(project_dir / "tests" / f"test_{pkg}.py", f'"""Tests for {slug} skill."""\nimport asyncio\nimport sys\nsys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))\n\nfrom {pkg} import get_manifest, do_thing\n\n\ndef test_manifest():\n    m = get_manifest()\n    assert m.name == "{pkg}"\n    assert len(m.tools) > 0\n\n\ndef test_do_thing():\n    result = asyncio.run(do_thing(input="hello"))\n    assert "result" in result\n')
    _write(project_dir / "README.md", f"# {slug}\n\n{description}\n\n## Install\nCopy `{pkg}.py` to your NeuralClaw user skills directory.\n\n## Test\n```\npytest tests/ -v\n```\n")
    return [f"{pkg}.py", "tests/", "README.md"]


def _scaffold_generic(project_dir: Path, slug: str, description: str, author: str) -> list[str]:
    _write(project_dir / "main.py", f'"""Main module for {slug}."""\n\nif __name__ == "__main__":\n    print("Hello from {slug}")\n')
    _write(project_dir / ".gitignore", "__pycache__/\n*.pyc\n.env\n*.egg-info/\ndist/\nbuild/\n")
    return ["main.py", ".gitignore"]


_TEMPLATE_FACTORIES = {
    "python-service": (_scaffold_python_service, "python -m src.{slug}.main", "Production Python service with src/, tests/, docs/, Dockerfile"),
    "python-lib": (_scaffold_python_lib, "pytest tests/ -v", "Python library with typed stubs"),
    "fastapi": (_scaffold_fastapi, "uvicorn app.main:app --reload", "FastAPI app with routers and models"),
    "cli-tool": (_scaffold_cli_tool, "python src/cli.py --help", "argparse CLI tool"),
    "data-pipeline": (_scaffold_data_pipeline, "python src/pipeline.py", "Data processing pipeline with notebooks"),
    "agent-skill": (_scaffold_agent_skill, "pytest tests/ -v", "NeuralClaw skill plugin with tests"),
    "generic": (_scaffold_generic, "python main.py", "Flat generic project structure"),
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def scaffold_project(
    project_name: str,
    template: str = "python-service",
    description: str = "",
    author: str = "",
    claim_directory: bool = True,
    **kwargs,
) -> dict:
    """
    Create a complete project from a template with AGENTS.md and README.md.
    """
    if template not in _TEMPLATE_FACTORIES:
        return {
            "error": f"Unknown template '{template}'.",
            "available": list(_TEMPLATE_FACTORIES.keys()),
        }

    slug, project_dir, err = _resolve_dir(project_name)
    if err:
        return err

    assert project_dir is not None and slug is not None

    if project_dir.exists():
        return {"error": f"Directory already exists: {project_dir}", "path": str(project_dir)}

    description = description or f"{slug} project"
    author = author or _agent_name

    # Optionally claim the directory before writing
    if claim_directory and _workspace_coordinator:
        claim = await _workspace_coordinator.claim(str(project_dir), _agent_name, purpose=f"scaffold {template}")
        if claim is None:
            existing = await _workspace_coordinator.get_claim(str(project_dir))
            return {
                "error": f"Directory path claimed by '{existing.agent_name if existing else 'unknown'}'",
                "path": str(project_dir),
            }

    factory_fn, run_cmd_template, template_description = _TEMPLATE_FACTORIES[template]

    # Resolve run command (replace {slug} placeholder)
    run_cmd = run_cmd_template.replace("{slug}", slug)

    try:
        layout = factory_fn(project_dir, slug, description, author)

        # Write AGENTS.md
        agents_md_content = _agents_md(slug, description, template, layout, run_cmd)
        _write(project_dir / "AGENTS.md", agents_md_content)

        # Write README.md
        readme = f"# {slug}\n\n{description}\n\n## Template\n{template_description}\n\n## Quick start\n```\n{run_cmd}\n```\n\n## Structure\n" + "\n".join(f"- `{l}`" for l in layout) + "\n"
        _write(project_dir / "README.md", readme)

        # Write .gitignore
        _write(project_dir / ".gitignore", "__pycache__/\n*.pyc\n.env\n*.egg-info/\ndist/\nbuild/\n.DS_Store\n")

    except Exception as e:
        return {"error": f"Scaffold failed: {e}", "path": str(project_dir)}

    return {
        "success": True,
        "project_name": slug,
        "path": str(project_dir),
        "template": template,
        "files_created": layout + ["AGENTS.md", "README.md", ".gitignore"],
        "run_cmd": run_cmd,
        "note": "AGENTS.md written — future agents can read it to understand this project.",
    }


async def list_projects(**kwargs) -> dict:
    """List all scaffolded projects (directories with AGENTS.md) under the apps dir."""
    if not _apps_dir.exists():
        return {"projects": [], "apps_dir": str(_apps_dir)}

    projects = []
    try:
        for entry in sorted(_apps_dir.iterdir()):
            if not entry.is_dir():
                continue
            agents_md = entry / "AGENTS.md"
            if not agents_md.exists():
                continue
            try:
                content = agents_md.read_text(encoding="utf-8", errors="replace")
                # Extract template and created_by from AGENTS.md
                template = "unknown"
                created_by = "unknown"
                for line in content.splitlines():
                    if line.startswith("**Template:**"):
                        template = line.split("`")[1] if "`" in line else "unknown"
                    elif line.startswith("**Created by:**"):
                        created_by = line.split("`")[1] if "`" in line else "unknown"
                projects.append({
                    "name": entry.name,
                    "path": str(entry),
                    "template": template,
                    "created_by": created_by,
                    "has_agents_md": True,
                })
            except Exception:
                projects.append({"name": entry.name, "path": str(entry), "has_agents_md": True})
    except Exception as e:
        return {"error": str(e), "projects": []}

    return {"total": len(projects), "apps_dir": str(_apps_dir), "projects": projects}


async def get_project_info(project_name: str, **kwargs) -> dict:
    """Return AGENTS.md content and directory listing for a project."""
    slug = _slugify(project_name)
    project_dir = _apps_dir / slug
    if not project_dir.exists():
        return {"error": f"Project '{slug}' not found at {project_dir}"}

    agents_md_path = project_dir / "AGENTS.md"
    agents_md = ""
    if agents_md_path.exists():
        try:
            agents_md = agents_md_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    try:
        entries = [e.name + ("/" if e.is_dir() else "") for e in sorted(project_dir.iterdir())]
    except Exception:
        entries = []

    # Active workspace claim
    claim_info = None
    if _workspace_coordinator:
        try:
            c = await _workspace_coordinator.get_claim(str(project_dir))
            if c:
                claim_info = {"agent": c.agent_name, "purpose": c.purpose, "claimed_at": c.claimed_at}
        except Exception:
            pass

    return {
        "name": slug,
        "path": str(project_dir),
        "agents_md": agents_md,
        "entries": entries,
        "workspace_claim": claim_info,
    }


async def add_to_project(
    project_name: str,
    component: str,
    **kwargs,
) -> dict:
    """
    Add a component to an existing project.

    Components: dockerfile, ci_github, ci_gitlab, makefile, test
    """
    slug = _slugify(project_name)
    project_dir = _apps_dir / slug
    if not project_dir.exists():
        return {"error": f"Project '{slug}' not found at {project_dir}"}

    component = component.lower().strip()
    created: list[str] = []

    try:
        if component == "dockerfile":
            p = project_dir / "Dockerfile"
            if not p.exists():
                _write(p, 'FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true\nCMD ["python", "main.py"]\n')
                created.append("Dockerfile")

        elif component == "ci_github":
            p = project_dir / ".github" / "workflows" / "ci.yml"
            if not p.exists():
                _write(p, f'name: CI\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: "3.12"\n      - run: pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true\n      - run: pytest tests/ -v\n')
                created.append(".github/workflows/ci.yml")

        elif component == "ci_gitlab":
            p = project_dir / ".gitlab-ci.yml"
            if not p.exists():
                _write(p, 'image: python:3.12-slim\nstages:\n  - test\ntest:\n  stage: test\n  script:\n    - pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true\n    - pytest tests/ -v\n')
                created.append(".gitlab-ci.yml")

        elif component == "makefile":
            p = project_dir / "Makefile"
            if not p.exists():
                _write(p, '.PHONY: install test lint clean\n\ninstall:\n\tpip install -e .\n\ntest:\n\tpytest tests/ -v\n\nlint:\n\truff check .\n\nclean:\n\trm -rf __pycache__ .pytest_cache dist build *.egg-info\n')
                created.append("Makefile")

        elif component == "test":
            test_dir = project_dir / "tests"
            test_dir.mkdir(exist_ok=True)
            init = test_dir / "__init__.py"
            if not init.exists():
                _write(init, "")
                created.append("tests/__init__.py")
            placeholder = test_dir / "test_placeholder.py"
            if not placeholder.exists():
                _write(placeholder, "def test_placeholder():\n    assert True\n")
                created.append("tests/test_placeholder.py")

        else:
            return {
                "error": f"Unknown component '{component}'.",
                "available": ["dockerfile", "ci_github", "ci_gitlab", "makefile", "test"],
            }

    except Exception as e:
        return {"error": str(e)}

    if not created:
        return {"note": f"Component '{component}' already exists — nothing added.", "project": slug}

    return {"success": True, "project": slug, "component": component, "created": created}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="project_scaffold",
        description=(
            "Create complete project structures from scratch with AGENTS.md, README, CI stubs, and "
            "workspace coordination. Templates: python-service, fastapi, cli-tool, data-pipeline, agent-skill."
        ),
        version="0.1.0",
        capabilities=[Capability.FILESYSTEM_READ, Capability.FILESYSTEM_WRITE],
        tools=[
            ToolDefinition(
                name="scaffold_project",
                description=(
                    "Scaffold a new project directory from a template. Includes AGENTS.md (so agents know "
                    "what the project is), README, and proper directory structure. Templates: "
                    "python-service, python-lib, fastapi, cli-tool, data-pipeline, agent-skill, generic."
                ),
                parameters=[
                    ToolParameter(name="project_name", type="string", description="Project name (becomes directory slug)", required=True),
                    ToolParameter(name="template", type="string", description="Template: python-service | python-lib | fastapi | cli-tool | data-pipeline | agent-skill | generic", required=False, default="python-service", enum=["python-service", "python-lib", "fastapi", "cli-tool", "data-pipeline", "agent-skill", "generic"]),
                    ToolParameter(name="description", type="string", description="Short project description", required=False, default=""),
                    ToolParameter(name="author", type="string", description="Author name", required=False, default=""),
                    ToolParameter(name="claim_directory", type="boolean", description="Claim the directory for this agent before writing (default true)", required=False, default=True),
                ],
                handler=scaffold_project,
            ),
            ToolDefinition(
                name="list_projects",
                description="List all scaffolded projects (directories with AGENTS.md) in the apps workspace.",
                parameters=[],
                handler=list_projects,
            ),
            ToolDefinition(
                name="get_project_info",
                description="Get AGENTS.md content, directory listing, and workspace claim status for a project.",
                parameters=[
                    ToolParameter(name="project_name", type="string", description="Project name", required=True),
                ],
                handler=get_project_info,
            ),
            ToolDefinition(
                name="add_to_project",
                description="Add a component to an existing project: dockerfile, ci_github, ci_gitlab, makefile, or test.",
                parameters=[
                    ToolParameter(name="project_name", type="string", description="Project name", required=True),
                    ToolParameter(name="component", type="string", description="Component to add: dockerfile | ci_github | ci_gitlab | makefile | test", required=True, enum=["dockerfile", "ci_github", "ci_gitlab", "makefile", "test"]),
                ],
                handler=add_to_project,
            ),
        ],
    )
