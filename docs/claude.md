# Running FinBot with Claude (Anthropic)

FinBot supports Anthropic Claude as an LLM provider. This page covers configuration, model selection, and notes on how the integration works.

## Quick setup

**1. Install dependencies** (already included in `pyproject.toml`):

```bash
uv sync
```

**2. Set environment variables** in your `.env`:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_DEFAULT_MODEL=claude-sonnet-4-6
```

**3. Run the platform normally:**

```bash
uv run python run.py
```

Or with Docker:

```bash
# Edit .env as above, then:
docker compose up
```

That's it. All AI agent challenges will now use Claude.

---

## Environment variables

| Variable            | Required | Example                 | Description                                  |
| ------------------- | -------- | ----------------------- | -------------------------------------------- |
| `LLM_PROVIDER`      | Yes      | `anthropic`             | Selects the Anthropic client                 |
| `ANTHROPIC_API_KEY` | Yes      | `sk-ant-...`            | API key from [console.anthropic.com](https://console.anthropic.com) |
| `LLM_DEFAULT_MODEL` | Yes      | `claude-sonnet-4-6`     | Claude model ID (see table below)            |
| `LLM_MAX_TOKENS`    | No       | `5000`                  | Max output tokens per call (default: 5000)   |
| `LLM_TIMEOUT`       | No       | `60`                    | Request timeout in seconds (default: 60)     |
| `LLM_DEFAULT_TEMPERATURE` | No | `1`                    | Clamped to 0–1 for Claude (default: 1)       |

---

## Recommended models

| Model ID               | Best for                                      |
| ---------------------- | --------------------------------------------- |
| `claude-sonnet-4-6`    | General use — best balance of speed and capability (recommended) |
| `claude-opus-4-8`      | Maximum capability for complex multi-step agent tasks |
| `claude-haiku-4-5-20251001` | Fast and low-cost; lighter challenges     |

Set `LLM_DEFAULT_MODEL` to any of these. Individual agents do not override the model unless explicitly configured.

---

## How it works

The Anthropic client (`finbot/core/llm/anthropic_client.py`) implements the same `chat(LLMRequest) → LLMResponse` interface as the OpenAI client. The agent layer is unaware of the underlying provider.

The main translation the client handles:

| Internal format (OpenAI Responses API) | Anthropic Messages API |
| --- | --- |
| `{"role": "system", "content": "..."}` | `system` top-level parameter |
| `{"role": "user"/"assistant", "content": "..."}` | `messages` array entry |
| `{"type": "function_call", "call_id": ..., ...}` | `{"type": "tool_use", "id": ..., ...}` block in assistant message |
| `{"type": "function_call_output", "call_id": ..., "output": "..."}` | `{"type": "tool_result", "tool_use_id": ..., ...}` block in user message |

Tool definitions are converted from OpenAI's `parameters` field to Anthropic's `input_schema`.

---

## Switching providers at runtime

`LLM_PROVIDER` is read at startup. To switch providers, update `.env` and restart the server. Supported values:

| `LLM_PROVIDER` | Notes |
| --- | --- |
| `openai` | Default. Requires `OPENAI_API_KEY`. |
| `anthropic` | Requires `ANTHROPIC_API_KEY` and a Claude model in `LLM_DEFAULT_MODEL`. |
| `ollama` | Requires a running Ollama instance. Set `OLLAMA_BASE_URL`. |

---

## Troubleshooting

**`ANTHROPIC_API_KEY` is empty or invalid**
The agent will fail immediately with an authentication error. Verify the key at [console.anthropic.com](https://console.anthropic.com).

**`LLM_DEFAULT_MODEL` is set to an OpenAI model name (e.g. `gpt-5-nano`)**
Claude will reject an unknown model ID. Update `LLM_DEFAULT_MODEL` to a valid Claude model (e.g. `claude-sonnet-4-6`).

**Temperature out of range**
Claude's temperature is 0–1. If `LLM_DEFAULT_TEMPERATURE` is set above 1 (the OpenAI range allows up to 2), the client automatically clamps it to 1.

**`overloaded_error` or rate limits**
Claude has per-minute token limits. Reduce `AGENT_MAX_ITERATIONS` or `LLM_MAX_TOKENS` in `.env` if you hit limits during multi-tool agent runs.
