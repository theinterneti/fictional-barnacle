"""Smart Router adapter for TTA simulation harness.

This adapter wraps the Node.js smart-router to implement the LLMClient protocol.
"""

import subprocess
from pathlib import Path
from typing import Any

from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount

SMART_ROUTER_PATH = Path("/home/theinterneti/Repos/openrouter-smart-router")


class SmartRouterLLMClient:
    """Adapter that uses smart-router as the LLM backend.

    Wraps the Node.js smart-router CLI to implement the LLMClient protocol
    for use in TTA's simulation harness.
    """

    def __init__(self, task_type: str = "simple"):
        self.task_type = task_type
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Generate a response using the smart router."""

        # Extract user message content
        user_content = ""
        for msg in messages:
            if msg.role.value == "user":
                user_content = msg.content
                break

        if not user_content:
            user_content = messages[-1].content if messages else ""

        # Build the smart-router command
        cmd = [
            "node",
            str(SMART_ROUTER_PATH / "dist" / "src" / "cli.js"),
            "chat",
            "--task",
            self.task_type,
            "--",  # Pass message after options
            user_content,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(SMART_ROUTER_PATH),
            )

            if result.returncode != 0:
                # Fallback to mock response on error
                return self._mock_response(role, messages, params)

            # Parse response - look for the actual response in output
            response_text = self._extract_response(result.stdout)

            self.call_history.append(
                {
                    "method": "generate",
                    "role": role,
                    "messages": messages,
                    "response": response_text,
                }
            )

            # Estimate tokens
            prompt_tokens = sum(len(m.content.split()) for m in messages)
            completion_tokens = len(response_text.split())

            return LLMResponse(
                content=response_text,
                model_used="smart-router",
                token_count=TokenCount(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
                latency_ms=100.0,  # Estimated
                tier_used="primary",
            )

        except Exception as e:
            # Fallback to mock on any error
            return self._mock_response(role, messages, params, error=str(e))

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Stream a response - currently buffers like TTA's architecture."""
        # For now, use generate and buffer (matching TTA's buffer-then-stream)
        return await self.generate(role, messages, params)

    def _extract_response(self, output: str) -> str:
        """Extract the response text from smart-router output."""
        lines = output.split("\n")
        # Look for response lines after the model name
        in_response = False
        response_parts = []

        for line in lines:
            if "Response:" in line:
                in_response = True
                continue
            if in_response and line.strip():
                response_parts.append(line.strip())

        if response_parts:
            return " ".join(response_parts[:3])  # First few lines

        # Fallback: return last non-empty lines
        non_empty = [
            line for line in lines if line.strip() and not line.startswith(" ")
        ]
        return " ".join(non_empty[-2:]) if non_empty else "Response from smart router"

    def _mock_response(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        error: str | None = None,
    ) -> LLMResponse:
        """Fallback mock response when smart-router fails."""
        prompt_tokens = sum(len(m.content.split()) for m in messages)

        return LLMResponse(
            content=(
                f"[Smart Router unavailable: "
                f"{error or 'unknown error'}] Using fallback."
            ),
            model_used="smart-router-fallback",
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=10,
                total_tokens=prompt_tokens + 10,
            ),
            latency_ms=1.0,
            tier_used="primary",
        )


def create_smart_router_client(task_type: str = "simple") -> SmartRouterLLMClient:
    """Factory function to create the smart router client."""
    return SmartRouterLLMClient(task_type=task_type)
