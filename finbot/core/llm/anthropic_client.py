"""Anthropic Claude Client"""

import json
import logging
from typing import Any

import anthropic

from finbot.config import settings
from finbot.core.data.models import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Anthropic Claude Client"""

    def __init__(self) -> None:
        self.default_model = settings.LLM_DEFAULT_MODEL
        self.default_temperature = settings.LLM_DEFAULT_TEMPERATURE
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool definitions to Anthropic format."""
        result = []
        for tool in tools:
            if tool.get("type") == "function":
                result.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                )
        return result

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert internal messages (OpenAI Responses API format) to Anthropic format.

        The internal format uses OpenAI Responses API conventions:
          - {"role": "system"|"user"|"assistant", "content": "..."}
          - {"type": "function_call", "name": ..., "call_id": ..., "arguments": "json_str"}
          - {"type": "function_call_output", "call_id": ..., "output": "..."}

        Anthropic requires:
          - system as a top-level parameter (string)
          - alternating user/assistant messages
          - tool calls as {"type": "tool_use"} blocks inside assistant content lists
          - tool results as {"type": "tool_result"} blocks inside user content lists

        Returns (system_prompt, anthropic_messages).
        """
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            if msg.get("role") == "system":
                system_parts.append(str(msg.get("content", "")))
                i += 1
                continue

            if msg.get("role") in ("user", "assistant"):
                role = msg["role"]
                content = msg.get("content", "")
                # Merge consecutive same-role messages to satisfy Anthropic's alternation rule
                if anthropic_messages and anthropic_messages[-1]["role"] == role:
                    prev = anthropic_messages[-1]["content"]
                    if isinstance(prev, str):
                        anthropic_messages[-1]["content"] = prev + "\n" + content
                    elif isinstance(prev, list):
                        prev.append({"type": "text", "text": content})
                else:
                    anthropic_messages.append({"role": role, "content": content})
                i += 1
                continue

            if msg.get("type") == "function_call":
                # Collect consecutive function_calls into one assistant message
                tool_uses: list[dict[str, Any]] = []
                while i < len(messages) and messages[i].get("type") == "function_call":
                    fc = messages[i]
                    raw_args = fc.get("arguments", "{}")
                    parsed_args = (
                        json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                    tool_uses.append(
                        {
                            "type": "tool_use",
                            "id": fc["call_id"],
                            "name": fc["name"],
                            "input": parsed_args,
                        }
                    )
                    i += 1
                anthropic_messages.append({"role": "assistant", "content": tool_uses})
                continue

            if msg.get("type") == "function_call_output":
                # Collect consecutive outputs into one user message
                tool_results: list[dict[str, Any]] = []
                while i < len(messages) and messages[i].get("type") == "function_call_output":
                    fco = messages[i]
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": fco["call_id"],
                            "content": str(fco.get("output", "")),
                        }
                    )
                    i += 1
                anthropic_messages.append({"role": "user", "content": tool_results})
                continue

            i += 1

        return "\n\n".join(system_parts), anthropic_messages

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """Chat with Anthropic Claude."""
        try:
            model = request.model or self.default_model
            # Anthropic temperature is 0-1; clamp in case the config default exceeds 1
            temperature = min(
                1.0,
                self.default_temperature if request.temperature is None else request.temperature,
            )

            input_list: list[dict[str, Any]] = list(request.messages) if request.messages else []
            system_prompt, anthropic_messages = self._convert_messages(input_list)

            if request.output_json_schema:
                json_hint = (
                    f"\n\nRespond with valid JSON matching this schema: "
                    f"{json.dumps(request.output_json_schema.get('schema', {}))}"
                )
                system_prompt = (system_prompt + json_hint).strip()

            create_params: dict[str, Any] = {
                "model": model,
                "max_tokens": settings.LLM_MAX_TOKENS,
                "temperature": temperature,
                "messages": anthropic_messages,
            }

            if system_prompt:
                create_params["system"] = system_prompt

            if request.tools:
                create_params["tools"] = self._convert_tools(request.tools)

            response = await self._client.messages.create(**create_params)

            if not response:
                logger.warning("Invalid Anthropic response: response is None")
                return LLMResponse(
                    content="",
                    provider="anthropic",
                    success=False,
                    messages=input_list,
                    tool_calls=[],
                )

            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            new_entries: list[dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    new_entries.append({"role": "assistant", "content": block.text})
                elif block.type == "tool_use":
                    tool_calls.append(
                        {
                            "name": block.name,
                            "call_id": block.id,
                            "arguments": block.input,
                        }
                    )
                    # Store in internal format so base agent can append function_call_output
                    new_entries.append(
                        {
                            "type": "function_call",
                            "name": block.name,
                            "call_id": block.id,
                            "arguments": json.dumps(block.input),
                        }
                    )

            metadata: dict[str, Any] = {
                "response_id": response.id,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }

            return LLMResponse(
                content=" ".join(text_parts) if text_parts else None,
                provider="anthropic",
                success=True,
                metadata=metadata,
                messages=input_list + new_entries,
                tool_calls=tool_calls if tool_calls else None,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Anthropic chat failed: %s", e)
            raise Exception(f"Anthropic chat failed: {e}") from e  # pylint: disable=broad-exception-raised
