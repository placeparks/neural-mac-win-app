"""Multimodal backend processing — STT, vision interpretation, recording analysis."""

from __future__ import annotations
import json, time, hashlib, logging
from typing import Any
from pathlib import Path

logger = logging.getLogger("neuralclaw.adaptive.multimodal_processing")

class MultimodalProcessor:
    """Processes multimodal inputs using available models.

    Connects to the LLM provider for vision tasks and optional
    STT services for audio transcription. Results are fed back
    into the multimodal router to update input records.
    """

    def __init__(self, *, provider: Any = None, router: Any = None, bus: Any = None) -> None:
        self._provider = provider  # LLM provider with vision support
        self._router = router      # MultimodalRouter instance
        self._bus = bus

    def set_provider(self, provider: Any) -> None:
        self._provider = provider

    def set_router(self, router: Any) -> None:
        self._router = router

    async def process_voice(self, input_record: dict) -> dict:
        """Process voice input — transcribe if needed, then extract action."""
        input_id = input_record.get("input_id", "")
        transcription = input_record.get("transcription")
        audio_path = input_record.get("source_path")

        if not transcription and audio_path:
            # Attempt STT using provider if it supports audio
            transcription = await self._attempt_stt(audio_path)

        if not transcription:
            return {"ok": False, "input_id": input_id, "error": "No transcription available and STT failed"}

        # Extract actionable intent from transcription
        action = await self._extract_action_from_text(transcription, context="voice command")

        if self._router:
            await self._router._update_status(
                input_id, "completed",
                extracted_action=action or transcription)

        return {
            "ok": True,
            "input_id": input_id,
            "transcription": transcription,
            "extracted_action": action or transcription,
            "status": "completed",
        }

    async def process_screenshot(self, input_record: dict) -> dict:
        """Process screenshot — use vision model to extract actions."""
        input_id = input_record.get("input_id", "")
        image_path = input_record.get("source_path")
        description = input_record.get("transcription", "")
        metadata = input_record.get("metadata", {})

        # Try vision analysis
        analysis = await self._analyze_image(image_path, metadata.get("image_b64_hash"), description)

        if not analysis:
            analysis = f"Screenshot captured. Description: {description}" if description else "Screenshot captured for review."

        action = await self._extract_action_from_text(analysis, context="screenshot analysis")

        if self._router:
            await self._router._update_status(
                input_id, "completed",
                extracted_action=action or analysis)

        return {
            "ok": True,
            "input_id": input_id,
            "analysis": analysis,
            "extracted_action": action or analysis,
            "status": "completed",
        }

    async def process_recording(self, input_record: dict) -> dict:
        """Process screen recording — extract automation candidates."""
        input_id = input_record.get("input_id", "")
        recording_path = input_record.get("source_path", "")

        # For recordings, we generate an analysis summary
        # In production this would do frame-by-frame analysis
        analysis = await self._analyze_recording(recording_path)

        if self._router:
            await self._router._update_status(
                input_id, "completed",
                extracted_action=analysis or "Recording analyzed")

        return {
            "ok": True,
            "input_id": input_id,
            "analysis": analysis,
            "automation_candidates": self._extract_automation_candidates(analysis),
            "status": "completed",
        }

    async def process_diagram(self, input_record: dict) -> dict:
        """Process diagram — interpret into structured workflow/plan."""
        input_id = input_record.get("input_id", "")
        diagram_path = input_record.get("source_path")
        metadata = input_record.get("metadata", {})

        interpretation = await self._interpret_diagram(diagram_path, metadata)

        if self._router:
            await self._router._update_status(
                input_id, "completed",
                extracted_action=interpretation or "Diagram interpreted")

        return {
            "ok": True,
            "input_id": input_id,
            "interpretation": interpretation,
            "status": "completed",
        }

    async def process_pending(self) -> list[dict]:
        """Process all pending multimodal inputs."""
        if not self._router:
            return []

        results: list[dict] = []
        pending = await self._router.list_inputs()
        for record in pending:
            if record.get("status") not in ("received", "processing"):
                continue

            input_type = record.get("input_type")
            try:
                if input_type == "voice":
                    result = await self.process_voice(record)
                elif input_type == "screenshot":
                    result = await self.process_screenshot(record)
                elif input_type == "recording":
                    result = await self.process_recording(record)
                elif input_type == "diagram":
                    result = await self.process_diagram(record)
                else:
                    continue
                results.append(result)
            except Exception as e:
                logger.error("Failed to process %s input %s: %s", input_type, record.get("input_id"), e)
                if self._router:
                    await self._router._update_status(record["input_id"], "failed")
                results.append({"ok": False, "input_id": record.get("input_id"), "error": str(e)})

        return results

    # -- Internal processing methods --

    async def _attempt_stt(self, audio_path: str) -> str | None:
        """Attempt speech-to-text transcription."""
        if not self._provider:
            return None
        # Check if provider supports audio/whisper-style transcription
        if hasattr(self._provider, "transcribe"):
            try:
                result = await self._provider.transcribe(audio_path)
                return str(result) if result else None
            except Exception as e:
                logger.warning("STT failed: %s", e)
        return None

    async def _analyze_image(self, image_path: str | None, b64_hash: str | None, description: str) -> str | None:
        """Analyze an image using vision model."""
        if not self._provider:
            return None
        if not hasattr(self._provider, "complete"):
            return None

        try:
            messages = [
                {"role": "system", "content": "You are analyzing a screenshot. Describe what you see and suggest what actions the user might want to take based on the UI state."},
                {"role": "user", "content": f"Analyze this screenshot. Context: {description}" if description else "Analyze this screenshot and describe what actions could be taken."},
            ]
            # If provider supports vision, it would handle image content
            # For now, use text-based analysis of the description
            if description:
                response = await self._provider.complete(messages=messages)
                return str(getattr(response, "content", "")) or None
        except Exception as e:
            logger.warning("Image analysis failed: %s", e)
        return None

    async def _analyze_recording(self, recording_path: str) -> str:
        """Analyze a screen recording."""
        # In production, this would extract keyframes and analyze each
        path = Path(recording_path) if recording_path else None
        if path and path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            return f"Recording at {recording_path} ({size_mb:.1f} MB) queued for frame analysis. Automation extraction will identify repeated UI patterns."
        return f"Recording reference: {recording_path}. Frame-by-frame analysis pending."

    async def _interpret_diagram(self, diagram_path: str | None, metadata: dict) -> str:
        """Interpret a diagram into structured form."""
        if not self._provider or not hasattr(self._provider, "complete"):
            return "Diagram queued for interpretation. Vision model required."

        try:
            messages = [
                {"role": "system", "content": "You interpret diagrams (flowcharts, architecture diagrams, wireframes) into structured descriptions that can be converted to code, workflows, or plans."},
                {"role": "user", "content": f"Interpret this diagram at: {diagram_path or 'provided inline'}. Extract the structure, flow, and key components."},
            ]
            response = await self._provider.complete(messages=messages)
            return str(getattr(response, "content", "")) or "Diagram interpretation pending."
        except Exception as e:
            logger.warning("Diagram interpretation failed: %s", e)
            return "Diagram interpretation failed. Manual review required."

    async def _extract_action_from_text(self, text: str, context: str = "") -> str | None:
        """Extract actionable intent from text using LLM."""
        if not self._provider or not text:
            return None
        if not hasattr(self._provider, "complete"):
            return None

        try:
            messages = [
                {"role": "system", "content": "Extract the core actionable task from the user's input. Return just the task description, nothing else. If no clear action, return the input summarized."},
                {"role": "user", "content": f"Context: {context}\nInput: {text[:500]}"},
            ]
            response = await self._provider.complete(messages=messages, max_tokens=200)
            return str(getattr(response, "content", "")).strip() or None
        except Exception:
            return None

    @staticmethod
    def _extract_automation_candidates(analysis: str) -> list[dict]:
        """Extract potential automation candidates from recording analysis."""
        candidates: list[dict] = []
        if not analysis:
            return candidates
        # Simple heuristic: look for repeated action patterns in analysis
        keywords = ["click", "type", "navigate", "select", "open", "close", "submit", "scroll"]
        for i, keyword in enumerate(keywords):
            if keyword in analysis.lower():
                candidates.append({
                    "action": keyword,
                    "confidence": 0.5,
                    "description": f"Detected '{keyword}' pattern in recording",
                })
        return candidates[:5]
