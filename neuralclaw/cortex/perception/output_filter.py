"""Prompt Armor v2 output screening."""

from __future__ import annotations

import re
from dataclasses import dataclass

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import SecurityConfig
from neuralclaw.cortex.perception.intake import Signal

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_PATTERN = re.compile(r"(?:(?<=\s)|^)(?:\+?\d[\d().\-\s]{8,}\d)(?=[\s.,;!?]|$)")
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*\{[^`]{0,1200}\"(?:tool|tool_name|tool_call|tool_calls|function|arguments)\"\s*:[^`]{0,1200}\}\s*```",
    re.I | re.S,
)
_TOOL_CALL_INLINE_PATTERN = re.compile(
    r"\{[^{}\n]{0,400}\"(?:tool|tool_name|tool_call|tool_calls|function|arguments)\"\s*:[^{}\n]{0,400}\}",
    re.I,
)
_REFUSAL_PREFIXES = (
    "i can't help with that",
    "i cannot help with that",
    "sorry, i can't help with that",
    "i can't assist with that",
    "i cannot assist with that",
    "i'm sorry, but i can't",
)
_JAILBREAK_CONFIRMATION_PREFIXES = (
    "sure, here's how to",
    "sure, here is how to",
    "absolutely, here's how to",
    "absolutely, here is how to",
    "okay, here's how to",
    "yes, here's how to",
)
_DANGEROUS_OUTPUT_HINTS = (
    "bypass",
    "exploit",
    "malware",
    "phishing",
    "steal credentials",
    "exfiltrate",
    "disable security",
    "evade detection",
    "make a bomb",
    "weapon",
    "payload",
    "rootkit",
    "ransomware",
)
_SAFE_REQUEST_HINTS = (
    "weather",
    "translate",
    "summarize",
    "help me write",
    "explain",
    "what is",
    "who is",
    "fix this code",
    "review this code",
)


@dataclass
class OutputFilterResult:
    safe: bool
    response: str
    flags: list[str]
    action: str


class OutputThreatFilter:
    """Screen model outputs before delivery."""

    def __init__(
        self,
        bus: NeuralBus | None = None,
        config: SecurityConfig | None = None,
    ) -> None:
        self._bus = bus
        self._config = config or SecurityConfig()
        self._canary_token = ""
        self._system_fragments: list[str] = []
        self._pii_patterns = [
            ("email", _EMAIL_PATTERN),
            ("phone", _PHONE_PATTERN),
            ("ssn", _SSN_PATTERN),
        ]
        for idx, pattern in enumerate(self._config.pii_patterns):
            try:
                self._pii_patterns.append((f"custom_pii_{idx + 1}", re.compile(pattern, re.I)))
            except re.error as exc:
                # Invalid regex — skip rather than crash at detection time
                import logging
                logging.getLogger("neuralclaw.output_filter").warning(
                    "Skipping invalid custom PII pattern %d: %s (%s)", idx + 1, pattern, exc,
                )

    def set_canary_token(self, token: str) -> None:
        """Register the active prompt canary."""
        self._canary_token = token.strip()

    def set_system_fragments(self, fragments: list[str]) -> None:
        """Register baseline system-prompt fragments for leak checks."""
        self._system_fragments = [fragment for fragment in fragments if fragment]

    async def screen(
        self,
        response: str,
        original_signal: Signal,
    ) -> OutputFilterResult:
        """Return a pass, sanitize, or block decision for the model response."""
        flags: list[str] = []
        action = "pass"
        sanitized = response
        prompt_fragments = self._resolve_prompt_fragments(original_signal)

        if self._config.canary_tokens and self._canary_token and self._canary_token in response:
            flags.extend(["canary_leak", "system_prompt_leakage"])
            action = "sanitize"
            sanitized = self._prompt_leak_replacement()

        if (
            action != "block"
            and self._config.output_prompt_leak_check
            and self._looks_like_prompt_leak(response, prompt_fragments)
        ):
            flags.append("system_prompt_leakage")
            action = "sanitize"
            sanitized = self._prompt_leak_replacement()

        if action != "block":
            tool_sanitized, tool_hits = self._strip_tool_call_payloads(sanitized)
            if tool_hits:
                flags.append("hallucinated_tool_call")
                action = "sanitize"
                sanitized = tool_sanitized

        if action != "block" and self._config.output_pii_detection:
            pii_sanitized, pii_flags = self._sanitize_pii(sanitized, original_signal.content)
            if pii_flags:
                flags.extend(pii_flags)
                action = "sanitize"
                sanitized = pii_sanitized

        if self._is_jailbreak_confirmation(sanitized):
            flags.append("jailbreak_confirmation")
            action = "block"
            sanitized = "I can't help with unsafe or policy-evading instructions."

        if self._is_excessive_refusal(sanitized, original_signal):
            flags.append("excessive_refusal")

        result = OutputFilterResult(
            safe=action != "block",
            response=sanitized,
            flags=self._dedupe(flags),
            action=action,
        )
        await self._publish(result, original_signal)
        return result

    def _resolve_prompt_fragments(self, signal: Signal) -> list[str]:
        context = getattr(signal, "context", {}) or {}
        signal_fragments = context.get("system_prompt_fragments", [])
        fragments = [fragment for fragment in signal_fragments if isinstance(fragment, str) and fragment]
        if fragments:
            return fragments
        return list(self._system_fragments)

    def _looks_like_prompt_leak(self, response: str, fragments: list[str]) -> bool:
        candidate = response.strip()
        if not candidate:
            return False
        candidate_words = self._tokenize(candidate)
        if len(candidate_words) < 6:
            return False

        for fragment in fragments:
            snippet = fragment.strip()
            if len(snippet) < 20:
                continue
            if snippet in candidate:
                return True
            fragment_words = self._tokenize(snippet)
            if len(fragment_words) < 6:
                continue
            overlap = candidate_words & fragment_words
            union = candidate_words | fragment_words
            similarity = len(overlap) / len(union) if union else 0.0
            if similarity >= 0.6 and len(overlap) >= 6:
                return True
        return False

    def _sanitize_pii(self, response: str, original_input: str) -> tuple[str, list[str]]:
        sanitized = response
        flags: list[str] = []
        input_hits = self._collect_input_hits(original_input)

        for label, pattern in self._pii_patterns:
            seen_replacement = False

            def replacer(match: re.Match[str]) -> str:
                nonlocal seen_replacement
                token = match.group(0)
                if token in input_hits:
                    return token
                seen_replacement = True
                return f"[REDACTED_{label.upper()}]"

            sanitized = pattern.sub(replacer, sanitized)
            if seen_replacement:
                flags.append(f"pii_{label}")

        return sanitized, flags

    def _collect_input_hits(self, text: str) -> set[str]:
        hits: set[str] = set()
        for _, pattern in self._pii_patterns:
            hits.update(match.group(0) for match in pattern.finditer(text))
        return hits

    def _strip_tool_call_payloads(self, response: str) -> tuple[str, bool]:
        sanitized = _TOOL_CALL_BLOCK_PATTERN.sub("[INTERNAL_TOOL_CALL_REMOVED]", response)
        sanitized = _TOOL_CALL_INLINE_PATTERN.sub("[INTERNAL_TOOL_CALL_REMOVED]", sanitized)
        return sanitized, sanitized != response

    def _is_jailbreak_confirmation(self, response: str) -> bool:
        lower = response.strip().lower()
        if not any(lower.startswith(prefix) for prefix in _JAILBREAK_CONFIRMATION_PREFIXES):
            return False
        return any(hint in lower for hint in _DANGEROUS_OUTPUT_HINTS)

    def _is_excessive_refusal(self, response: str, signal: Signal) -> bool:
        lower = response.strip().lower()
        if not any(lower.startswith(prefix) for prefix in _REFUSAL_PREFIXES):
            return False
        signal_lower = signal.content.lower()
        if getattr(signal, "threat_score", 0.0) >= 0.2:
            return False
        if any(hint in signal_lower for hint in _DANGEROUS_OUTPUT_HINTS):
            return False
        return any(hint in signal_lower for hint in _SAFE_REQUEST_HINTS) or "?" in signal.content

    def _prompt_leak_replacement(self) -> str:
        return "I can't share internal instructions, hidden prompt content, or security metadata."

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9_]{3,}", text.lower())}

    def _dedupe(self, flags: list[str]) -> list[str]:
        return list(dict.fromkeys(flags))

    async def _publish(self, result: OutputFilterResult, signal: Signal) -> None:
        if not self._bus:
            return
        severity = 0.0
        if result.action == "sanitize":
            severity = 0.75
        if result.action == "block":
            severity = 1.0
        await self._bus.publish(
            EventType.THREAT_SCREENED,
            {
                "signal_id": getattr(signal, "id", ""),
                "score": severity,
                "blocked": result.action == "block",
                "reasons": result.flags,
                "flags": result.flags,
                "action": result.action,
                "stage": "output",
                "source_trust": max(0.0, 1.0 - severity),
                "verifier_used": False,
                "verifier_action": "",
            },
            source="perception.output_filter",
        )
