"""Skill Graph -- dependency resolution, composition, and visualization."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from neuralclaw.skills.manifest import SkillManifest


class SkillNode:
    """A single node in the skill dependency graph."""

    def __init__(self, name: str, manifest: SkillManifest | None = None) -> None:
        self.name = name
        self.manifest = manifest
        self.dependencies: list[str] = []   # skill names this depends on
        self.dependents: list[str] = []     # skill names that depend on this
        self.capabilities: list[str] = []
        self.risk_level: str = "low"
        self.composition_metadata: dict[str, Any] = {}


class SkillGraph:
    """Directed acyclic graph of skill dependencies with topological
    resolution, cycle detection, and visualization export.

    Uses Kahn's algorithm for topological sort (consistent with the
    workflow engine precedent in ``neuralclaw.cortex.reasoning.workflow``).
    """

    def __init__(self) -> None:
        self._nodes: dict[str, SkillNode] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # from -> set[to]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_skill(
        self,
        manifest: SkillManifest,
        dependencies: list[str] | None = None,
        risk_level: str = "low",
        capabilities: list[str] | None = None,
    ) -> None:
        """Add a skill to the graph with optional dependency declarations."""
        name = manifest.name
        node = SkillNode(name=name, manifest=manifest)
        node.risk_level = risk_level
        node.capabilities = list(capabilities or [])
        node.dependencies = list(dependencies or [])
        self._nodes[name] = node

        # Register edges: dependency -> this skill (dependency must load first)
        for dep in node.dependencies:
            self._edges[dep].add(name)
            # Update the dependent's dependents list if it exists
            if dep in self._nodes:
                if name not in self._nodes[dep].dependents:
                    self._nodes[dep].dependents.append(name)
        # Update dependents lists for any existing nodes that depend on this one
        for other_name, other_node in self._nodes.items():
            if name in other_node.dependencies and name not in other_node.dependencies:
                pass  # already there
            if other_name in node.dependencies:
                if other_name in self._nodes and name not in self._nodes[other_name].dependents:
                    self._nodes[other_name].dependents.append(name)

    def remove_skill(self, name: str) -> None:
        """Remove a skill and all its edges from the graph."""
        if name not in self._nodes:
            return

        # Remove outgoing edges from this node
        if name in self._edges:
            del self._edges[name]

        # Remove this node from other nodes' edge sets and dependents lists
        for src, targets in list(self._edges.items()):
            targets.discard(name)

        # Clean up dependents lists
        for other_node in self._nodes.values():
            if name in other_node.dependents:
                other_node.dependents.remove(name)
            if name in other_node.dependencies:
                other_node.dependencies.remove(name)

        del self._nodes[name]

    # ------------------------------------------------------------------
    # Dependency resolution (Kahn's algorithm)
    # ------------------------------------------------------------------

    def _build_subgraph_in_degree(self, root: str) -> tuple[dict[str, int], set[str]]:
        """BFS to collect all transitive dependencies of *root*, returning
        in-degree map and the set of relevant nodes."""
        relevant: set[str] = set()
        queue: deque[str] = deque([root])
        while queue:
            current = queue.popleft()
            if current in relevant:
                continue
            relevant.add(current)
            if current in self._nodes:
                for dep in self._nodes[current].dependencies:
                    queue.append(dep)

        # Build in-degree map restricted to relevant nodes
        in_degree: dict[str, int] = {n: 0 for n in relevant}
        for n in relevant:
            if n in self._nodes:
                for dep in self._nodes[n].dependencies:
                    if dep in relevant:
                        in_degree[n] += 1
        return in_degree, relevant

    def resolve_dependencies(self, skill_name: str) -> list[str]:
        """Topological sort of dependencies using Kahn's algorithm.

        Returns an ordered list suitable for sequential loading (dependencies
        first).  Raises ``ValueError`` on cycles.
        """
        if skill_name not in self._nodes:
            raise KeyError(f"Skill '{skill_name}' not in graph")

        in_degree, relevant = self._build_subgraph_in_degree(skill_name)

        queue: deque[str] = deque(
            n for n, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            # For each node that depends on *node*, decrement in-degree
            for n in relevant:
                if n in self._nodes and node in self._nodes[n].dependencies:
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        queue.append(n)

        if len(order) != len(relevant):
            unresolved = relevant - set(order)
            raise ValueError(
                f"Cycle detected among skills: {', '.join(sorted(unresolved))}"
            )
        return order

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_graph(self) -> dict[str, Any]:
        """Validate the full graph: check for cycles, missing deps, orphans.

        Returns a report dict with ``valid`` bool, ``cycles``, ``missing``,
        and ``orphans`` lists.
        """
        report: dict[str, Any] = {
            "valid": True,
            "cycles": [],
            "missing": [],
            "orphans": [],
        }

        # Check for missing dependencies
        report["missing"] = self.find_missing_dependencies()
        if report["missing"]:
            report["valid"] = False

        # Full-graph cycle detection via Kahn's algorithm
        all_nodes = set(self._nodes.keys())
        in_degree: dict[str, int] = {n: 0 for n in all_nodes}
        for n, node in self._nodes.items():
            for dep in node.dependencies:
                if dep in in_degree:
                    in_degree[n] += 1

        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        visited: list[str] = []
        while queue:
            node = queue.popleft()
            visited.append(node)
            for target in self._edges.get(node, set()):
                if target in in_degree:
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        cycle_members = all_nodes - set(visited)
        if cycle_members:
            report["valid"] = False
            report["cycles"] = sorted(cycle_members)

        # Orphans: nodes with no dependencies and no dependents
        for name, node in self._nodes.items():
            has_deps = bool(node.dependencies)
            has_dependents = bool(node.dependents) or bool(self._edges.get(name))
            if not has_deps and not has_dependents:
                report["orphans"].append(name)

        return report

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def get_composition_chain(self, *skill_names: str) -> list[str]:
        """Get the ordered loading chain for composing multiple skills.

        Merges the dependency sub-graphs of all requested skills and
        returns a single topological order.
        """
        all_relevant: set[str] = set()
        for name in skill_names:
            if name not in self._nodes:
                raise KeyError(f"Skill '{name}' not in graph")
            _, relevant = self._build_subgraph_in_degree(name)
            all_relevant |= relevant

        # Kahn's on the merged subgraph
        in_degree: dict[str, int] = {n: 0 for n in all_relevant}
        for n in all_relevant:
            if n in self._nodes:
                for dep in self._nodes[n].dependencies:
                    if dep in all_relevant:
                        in_degree[n] += 1

        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for n in all_relevant:
                if n in self._nodes and node in self._nodes[n].dependencies:
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        queue.append(n)

        if len(order) != len(all_relevant):
            unresolved = all_relevant - set(order)
            raise ValueError(
                f"Cycle detected among skills: {', '.join(sorted(unresolved))}"
            )
        return order

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def to_visualization(self) -> dict[str, Any]:
        """Return a serializable graph structure for frontend visualization.

        Format::

            {
                "nodes": [{"id": str, "label": str, "risk_level": str,
                           "tool_count": int, "capabilities": [...]}],
                "edges": [{"from": str, "to": str, "type": "depends_on"}]
            }
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for name, node in self._nodes.items():
            tool_count = 0
            if node.manifest:
                tool_count = len(node.manifest.tools)
            nodes.append({
                "id": name,
                "label": name,
                "risk_level": node.risk_level,
                "tool_count": tool_count,
                "capabilities": node.capabilities,
            })

        for src, targets in self._edges.items():
            for tgt in sorted(targets):
                edges.append({
                    "from": src,
                    "to": tgt,
                    "type": "depends_on",
                })

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_skills_by_capability(self, capability: str) -> list[str]:
        """Find skills that declare a specific capability."""
        return [
            name
            for name, node in self._nodes.items()
            if capability in node.capabilities
        ]

    def find_missing_dependencies(self) -> list[dict[str, str]]:
        """Find declared dependencies that aren't registered in the graph."""
        missing: list[dict[str, str]] = []
        for name, node in self._nodes.items():
            for dep in node.dependencies:
                if dep not in self._nodes:
                    missing.append({"skill": name, "missing_dependency": dep})
        return missing

    async def auto_resolve_missing(self, forge: Any = None, scout: Any = None,
                                     candidate_dir: str | Path | None = None) -> list[dict[str, Any]]:
        """Auto-resolve missing dependencies using Forge/Scout.

        For each missing dependency, attempt to acquire it:
        - If the dep name contains API/github/package markers, use Scout
        - Otherwise use Forge

        Returns a list of resolution results.
        """
        from pathlib import Path as _Path
        missing = self.find_missing_dependencies()
        if not missing:
            return []

        results: list[dict[str, Any]] = []
        resolved_dir = _Path(candidate_dir) if candidate_dir else _Path.cwd() / ".neuralclaw" / "skills" / "resolved"
        resolved_dir.mkdir(parents=True, exist_ok=True)

        seen_deps: set[str] = set()
        for entry in missing:
            dep_name = entry["missing_dependency"]
            if dep_name in seen_deps:
                continue
            seen_deps.add(dep_name)

            result: dict[str, Any] = {
                "dependency": dep_name,
                "requested_by": entry["skill"],
                "strategy": "unknown",
                "success": False,
                "error": None,
            }

            # Choose strategy
            scout_markers = ("github", "api", "openapi", "graphql", "mcp", "pypi", "npm", "package")
            use_scout = scout is not None and any(m in dep_name.lower() for m in scout_markers)

            try:
                if use_scout and scout is not None:
                    result["strategy"] = "scout"
                    scout_result = await scout.scout(
                        dep_name,
                        activate=False,
                        skills_dir=resolved_dir,
                        registry_source="resolved",
                    )
                    forge_result = scout_result.forge_result if scout_result and hasattr(scout_result, "forge_result") else scout_result
                    result["success"] = bool(forge_result and getattr(forge_result, "success", False))
                    if result["success"]:
                        result["skill_path"] = str(getattr(forge_result, "file_path", ""))
                elif forge is not None:
                    result["strategy"] = "forge"
                    forge_result = await forge.forge_from_description(
                        f"Skill providing: {dep_name}",
                        use_case=f"Dependency required by skill '{entry['skill']}'",
                        activate=False,
                        skills_dir=resolved_dir,
                        registry_source="resolved",
                    )
                    result["success"] = bool(forge_result and getattr(forge_result, "success", False))
                    if result["success"]:
                        result["skill_path"] = str(getattr(forge_result, "file_path", ""))
                else:
                    result["strategy"] = "none"
                    result["error"] = "No Forge or Scout available"
            except Exception as e:
                result["error"] = str(e)

            results.append(result)

        return results
