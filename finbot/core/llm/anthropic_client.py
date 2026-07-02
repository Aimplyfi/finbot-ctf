"""Anthropic Claude client implementation."""

import json
import logging
from typing import Any

import anthropic

from finbot.config import settings
from finbot.core.data.models import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


MODELS_WITHOUT_TEMPERATURE = ("claude-opus-4-7", "claude-opus-4-8", "claude-fable-5", "claude-mythos-5")


def _supports_temperature(model: str) -> bool:
    return not any(model.startswith(m) for m in MODELS_WITHOUT_TEMPERATURE)


def convert_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-format tool definitions to Anthropic format."""
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


def convert_messages_to_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert OpenAI-style messages to Anthropic format.

    Handles: system messages, simple user/assistant text, function_call entries,
    and function_call_output entries. Returns (system_prompt, anthropic_messages).
    """
    system_prompt = None
    anthropic_messages: list[dict[str, Any]] = []

    i = 0
    while i < len(messages):
        msg = messages[i]

        # Extract system message as top-level param
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
            i += 1
            continue

        # Already in Anthropic list-content format — pass through
        if msg.get("role") in ("user", "assistant") and isinstance(
            msg.get("content"), list
        ):
            anthropic_messages.append(msg)
            i += 1
            continue

        # Simple user message
        if msg.get("role") == "user":
            anthropic_messages.append({"role": "user", "content": msg.get("content", "")})
            i += 1
            continue

        # Assistant text message — look ahead and collect any following function_call entries
        if msg.get("role") == "assistant":
            content_blocks: list[dict[str, Any]] = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})

            j = i + 1
            while j < len(messages) and messages[j].get("type") == "function_call":
                fc = messages[j]
                args = fc.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": fc["call_id"],
                        "name": fc["name"],
                        "input": args,
                    }
                )
                j += 1

            if content_blocks:
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            i = j
            continue

        # Standalone function_call(s) — group consecutive ones into one assistant message
        if msg.get("type") == "function_call":
            content_blocks = []
            j = i
            while j < len(messages) and messages[j].get("type") == "function_call":
                fc = messages[j]
                args = fc.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": fc["call_id"],
                        "name": fc["name"],
                        "input": args,
                    }
                )
                j += 1
            if content_blocks:
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            i = j
            continue

        # function_call_output(s) — group consecutive ones into one user message
        if msg.get("type") == "function_call_output":
            tool_results = []
            j = i
            while j < len(messages) and messages[j].get("type") == "function_call_output":
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": messages[j]["call_id"],
                        "content": str(messages[j].get("output", "")),
                    }
                )
                j += 1
            if tool_results:
                anthropic_messages.append({"role": "user", "content": tool_results})
            i = j
            continue

        # Unknown entry — skip
        i += 1

    return system_prompt, anthropic_messages


class AnthropicClient:
    """Anthropic Claude client with OpenAI-compatible LLMRequest/LLMResponse interface."""

    def __init__(self) -> None:
        self.default_model = settings.LLM_DEFAULT_MODEL
        self.default_temperature = settings.LLM_DEFAULT_TEMPERATURE
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """Send a chat request to Anthropic and return a normalised LLMResponse."""
        try:
            model = request.model or self.default_model
            temperature = (
                self.default_temperature
                if request.temperature is None
                else request.temperature
            )

            messages = list(request.messages) if request.messages else []

            system_prompt, anthropic_messages = convert_messages_to_anthropic(messages)

            create_params: dict[str, Any] = {
                "model": model,
                "max_tokens": settings.LLM_MAX_TOKENS,
                "messages": anthropic_messages,
            }
            if _supports_temperature(model):
                create_params["temperature"] = temperature

            if system_prompt:
                create_params["system"] = system_prompt

            # Structured JSON output — implemented via forced tool_choice
            if request.output_json_schema:
                schema = request.output_json_schema
                schema_name = schema.get("name", "json_output")
                create_params["tools"] = [
                    {
                        "name": schema_name,
                        "description": "Return structured JSON output",
                        "input_schema": schema.get("schema", {}),
                    }
                ]
                create_params["tool_choice"] = {"type": "tool", "name": schema_name}
            elif request.tools:
                create_params["tools"] = convert_tools_to_anthropic(request.tools)

            response = await self._client.messages.create(**create_params)

            text_content = ""
            tool_calls: list[dict[str, Any]] = []
            new_entries: list[dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    # If this was a JSON schema call, return the input as JSON text
                    if request.output_json_schema:
                        text_content = json.dumps(block.input)
                    else:
                        tool_calls.append(
                            {
                                "name": block.name,
                                "call_id": block.id,
                                "arguments": block.input,
                            }
                        )

            # Build updated messages in OpenAI-compat format so callers can append
            # function_call_output entries and pass them back on the next iteration.
            if text_content and not tool_calls:
                new_entries.append({"role": "assistant", "content": text_content})
            elif tool_calls:
                if text_content:
                    new_entries.append({"role": "assistant", "content": text_content})
                for tc in tool_calls:
                    new_entries.append(
                        {
                            "type": "function_call",
                            "name": tc["name"],
                            "call_id": tc["call_id"],
                            "arguments": json.dumps(tc["arguments"]),
                        }
                    )

            updated_messages = messages + new_entries

            return LLMResponse(
                content=text_content,
                provider="anthropic",
                success=True,
                messages=updated_messages,
                tool_calls=tool_calls if tool_calls else None,
            )

        except Exception as e:
            logger.error("Anthropic chat failed: %s", e)
            raise Exception(f"Anthropic chat failed: {e}") from e  # pylint: disable=broad-exception-raised
