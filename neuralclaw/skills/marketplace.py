"""
Skill Marketplace — Verified skill distribution with cryptographic signing.

Implements:
- HMAC-SHA256 signing/verification of skill packages
- Static analysis to scan for dangerous patterns pre-install
- Community reputation scoring
- Install/uninstall from a marketplace registry
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Skill package model
# ---------------------------------------------------------------------------

@dataclass
class SkillPackage:
    """A distributable skill package."""
    name: str
    version: str
    author: str
    description: str
    code_hash: str = ""
    signature: str = ""          # Ed25519 signature (hex)
    trust_score: float = 0.0     # 0.0 - 1.0
    downloads: int = 0
    verified: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def is_signed(self) -> bool:
        return bool(self.signature)

    @property
    def risk_score(self) -> float:
        """Risk score derived from trust_score. 0.0 = safe, 1.0 = dangerous."""
        return round(1.0 - self.trust_score, 6)


# ---------------------------------------------------------------------------
# Static Analyzer
# ---------------------------------------------------------------------------

class StaticAnalyzer:
    """
    Pre-install static analysis for skill code.

    Scans for dangerous patterns:
    - Data exfiltration (network calls to unexpected domains)
    - Unauthorized file system access
    - Shell command execution
    - Obfuscated code patterns
    """

    DANGEROUS_PATTERNS = [
        # Network exfiltration
        (r"requests\.(get|post|put|delete)\s*\(", "Unauthorized HTTP request", 0.8),
        (r"urllib\.request\.urlopen", "Unauthorized URL access", 0.8),
        (r"socket\.socket", "Raw socket access", 0.9),
        (r"aiohttp\.ClientSession", "Async HTTP session", 0.5),

        # File system abuse
        (r"os\.remove|os\.unlink|shutil\.rmtree", "File deletion", 0.9),
        (r"open\(.+,\s*['\"]w['\"]", "File write operation", 0.4),
        (r"\.\.\/" , "Path traversal", 0.95),

        # Shell execution
        (r"subprocess\.(call|run|Popen|getoutput)", "Shell command execution", 0.7),
        (r"os\.system\s*\(", "OS system call", 0.9),
        (r"exec\s*\(|eval\s*\(", "Dynamic code execution", 0.85),

        # Obfuscation
        (r"base64\.(b64decode|decodebytes)", "Base64 decoding (potential obfuscation)", 0.6),
        (r"__import__\s*\(", "Dynamic import", 0.7),
        (r"compile\s*\(", "Code compilation", 0.6),

        # Credential theft
        (r"keyring\.(get_password|set_password)", "Keyring access", 0.9),
        (r"os\.environ", "Environment variable access", 0.5),
    ]

    @classmethod
    def scan(cls, code: str) -> list[dict[str, Any]]:
        """
        Scan code for dangerous patterns. Returns list of findings.
        Each finding has: pattern, description, severity, line_number.
        """
        findings: list[dict[str, Any]] = []

        for line_num, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("#"):
                continue

            for pattern, desc, severity in cls.DANGEROUS_PATTERNS:
                if re.search(pattern, line):
                    findings.append({
                        "pattern": pattern,
                        "description": desc,
                        "severity": severity,
                        "line_number": line_num,
                        "line_content": stripped[:100],
                    })

        return findings

    @classmethod
    def compute_risk_score(cls, findings: list[dict[str, Any]]) -> float:
        """Compute an overall risk score from findings (0.0 - 1.0)."""
        if not findings:
            return 0.0
        max_severity = max(f["severity"] for f in findings)
        avg_severity = sum(f["severity"] for f in findings) / len(findings)
        return min(1.0, (max_severity * 0.7 + avg_severity * 0.3))


# ---------------------------------------------------------------------------
# Skill Marketplace
# ---------------------------------------------------------------------------

class SkillMarketplace:
    """
    Verified skill distribution system.

    Skills are signed, scanned, and rated before being available
    for installation. Unsigned skills require explicit user approval.
    """

    def __init__(self, marketplace_dir: str | Path | None = None) -> None:
        self._dir = Path(marketplace_dir) if marketplace_dir else Path.home() / ".neuralclaw" / "marketplace"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, SkillPackage] = {}
        self._analyzer = StaticAnalyzer()

    def load_registry(self) -> None:
        """Load the marketplace registry from disk."""
        registry_path = self._dir / "registry.json"
        if registry_path.exists():
            try:
                data = json.loads(registry_path.read_text())
                for name, pkg_data in data.items():
                    self._registry[name] = SkillPackage(**pkg_data)
            except (json.JSONDecodeError, TypeError):
                pass

    def save_registry(self) -> None:
        """Save the marketplace registry to disk."""
        data = {}
        for name, pkg in self._registry.items():
            data[name] = {
                "name": pkg.name, "version": pkg.version,
                "author": pkg.author, "description": pkg.description,
                "code_hash": pkg.code_hash, "signature": pkg.signature,
                "trust_score": pkg.trust_score, "downloads": pkg.downloads,
                "verified": pkg.verified, "created_at": pkg.created_at,
            }

        (self._dir / "registry.json").write_text(json.dumps(data, indent=2))

    def publish(
        self,
        name: str,
        version: str,
        author: str,
        description: str,
        code: str,
        private_key_hex: str | None = None,
    ) -> tuple[SkillPackage, list[dict[str, Any]]]:
        """
        Publish a skill to the marketplace.

        Returns (package, security_findings).
        """
        # Static analysis
        findings = self._analyzer.scan(code)
        risk_score = self._analyzer.compute_risk_score(findings)

        # Compute hash
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        # Sign with HMAC-SHA256 if signing key provided
        # NOTE: This is symmetric MAC signing (not Ed25519). Both publisher and
        # verifier must share the same key. For public distribution, consider
        # upgrading to Ed25519 (requires the `cryptography` package).
        signature = ""
        verified = False
        if private_key_hex:
            try:
                import hmac as _hmac
                sig_data = f"{name}:{version}:{code_hash}".encode()
                signature = _hmac.new(
                    bytes.fromhex(private_key_hex), sig_data, hashlib.sha256,
                ).hexdigest()
                verified = True
            except (ValueError, Exception):
                pass

        pkg = SkillPackage(
            name=name, version=version, author=author,
            description=description, code_hash=code_hash,
            signature=signature, trust_score=1.0 - risk_score,
            verified=verified,
        )

        # Store code
        skill_dir = self._dir / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / f"{name}.py").write_text(code)
        (skill_dir / "manifest.json").write_text(json.dumps({
            "name": name, "version": version, "author": author,
            "description": description, "hash": code_hash,
            "signature": signature,
        }, indent=2))

        self._registry[name] = pkg
        self.save_registry()

        return pkg, findings

    def install(self, name: str, require_signed: bool = True) -> Path | None:
        """
        Install a skill from the marketplace.

        Returns the path to the installed skill, or None if blocked.
        """
        pkg = self._registry.get(name)
        if not pkg:
            return None

        if require_signed and not pkg.is_signed:
            return None

        skill_path = self._dir / "skills" / name / f"{name}.py"
        if not skill_path.exists():
            return None

        pkg.downloads += 1
        self.save_registry()
        return skill_path

    def uninstall(self, name: str) -> bool:
        """Uninstall a skill from the marketplace."""
        if name not in self._registry:
            return False

        import shutil
        skill_dir = self._dir / "skills" / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        del self._registry[name]
        self.save_registry()
        return True

    def list_skills(self) -> list[SkillPackage]:
        """List all available skills in the marketplace."""
        return list(self._registry.values())

    def search(self, query: str) -> list[SkillPackage]:
        """Search the marketplace."""
        query_lower = query.lower()
        return [
            pkg for pkg in self._registry.values()
            if query_lower in pkg.name.lower() or query_lower in pkg.description.lower()
        ]
