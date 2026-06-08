"""
Unified model provider abstraction for Anthropic, OpenAI, and custom endpoints.

Supports:
  - Anthropic (claude-* models)
  - OpenAI (gpt-*, o1-*, o3-* models)
  - Any OpenAI-compatible endpoint via base_url (Ollama, vLLM, Together, etc.)

Usage:
    provider = create_provider(model="claude-sonnet-4-6-20250514")
    provider = create_provider(model="gpt-4o", api_key="sk-...")
    provider = create_provider(model="my-model", base_url="http://localhost:11434/v1", api_key="ollama")

    resp = provider.chat(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Hello"}],
        tools=[...],          # optional, provider-native format auto-converted
        max_tokens=8192,
    )
    print(resp.text, resp.tool_calls, resp.usage)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(env_path: Path | None = None) -> None:
    """Load .env file into os.environ (no dependencies required).

    Only sets variables that are not already set in the environment,
    so real env vars always take precedence.
    """
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


# Auto-load .env on import
load_dotenv()


# ---------------------------------------------------------------------------
# Unified response types
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" or "tool_use"
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: object = None  # original SDK response


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

class AnthropicProvider:
    def __init__(self, api_key: str | None = None):
        import anthropic
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        self.client = anthropic.Anthropic(**kwargs)

    def chat(self, model: str, system: str, messages: list,
             tools: list | None = None, max_tokens: int = 8192) -> ChatResponse:
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools  # already in Anthropic format

        response = self.client.messages.create(**kwargs)

        # Extract text
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        stop = "tool_use" if tool_calls else "end_turn"
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )

        return ChatResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=usage,
            model=response.model,
            raw=response,
        )

    def format_tool_results(self, tool_calls: list[ToolCall],
                            results: dict[str, str],
                            assistant_content) -> tuple[dict, dict]:
        """Return (assistant_message, user_message_with_tool_results)."""
        tool_results = []
        for tc in tool_calls:
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": results[tc.id],
            })
        return (
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": tool_results},
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAIProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        import openai
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)

    @staticmethod
    def _convert_tools(tools: list | None) -> list | None:
        """Convert Anthropic-format tool defs to OpenAI function-calling format."""
        if not tools:
            return None
        oai_tools = []
        for t in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return oai_tools

    def chat(self, model: str, system: str, messages: list,
             tools: list | None = None, max_tokens: int = 8192) -> ChatResponse:
        import json as _json

        # Convert messages: Anthropic format → OpenAI format
        oai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            oai_messages.append(self._convert_message(msg))

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        oai_tools = self._convert_tools(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools

        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        text = message.content or ""
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except _json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        stop = "tool_use" if tool_calls else "end_turn"
        u = response.usage
        usage = Usage(
            input_tokens=getattr(u, "prompt_tokens", 0) or 0,
            output_tokens=getattr(u, "completion_tokens", 0) or 0,
        )

        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=usage,
            model=response.model,
            raw=response,
        )

    def _convert_message(self, msg: dict) -> dict:
        """Convert a single Anthropic-style message to OpenAI format."""
        import json as _json

        role = msg["role"]
        content = msg["content"]

        # Simple string content
        if isinstance(content, str):
            return {"role": role, "content": content}

        # Anthropic assistant message with content blocks (text + tool_use)
        if role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if hasattr(block, "type"):
                    # SDK object
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": _json.dumps(block.input),
                            },
                        })
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": _json.dumps(block.get("input", {})),
                            },
                        })
            result = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_calls:
                result["tool_calls"] = tool_calls
            return result

        # Anthropic tool_result messages → OpenAI tool messages
        if role == "user" and isinstance(content, list):
            # Check if these are tool results
            if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                # OpenAI expects one message per tool result
                # Return the first one; caller should handle multi-result
                # Actually, we'll return a list marker and handle in the caller
                return {"role": "tool", "content": content[0].get("content", ""),
                        "tool_call_id": content[0].get("tool_use_id", ""),
                        "_multi": content}

        return {"role": role, "content": str(content)}

    def format_tool_results(self, tool_calls: list[ToolCall],
                            results: dict[str, str],
                            assistant_content) -> tuple[dict, list[dict]]:
        """Return (assistant_message, tool_result_messages).

        OpenAI uses separate messages per tool result, not a single user message.
        """
        import json as _json

        # Build assistant message with tool_calls
        text_parts = []
        oai_tool_calls = []
        if hasattr(assistant_content, '__iter__') and not isinstance(assistant_content, str):
            for block in assistant_content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        oai_tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": _json.dumps(block.input),
                            },
                        })

        assistant_msg = {
            "role": "assistant",
            "content": "\n".join(text_parts) or None,
            "tool_calls": oai_tool_calls,
        }

        tool_msgs = []
        for tc in tool_calls:
            tool_msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": results[tc.id],
            })

        return assistant_msg, tool_msgs


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def detect_provider(model: str) -> str:
    """Guess provider from model name."""
    model_lower = model.lower()
    if model_lower.startswith("claude"):
        return "anthropic"
    return "openai"


def create_provider(model: str, provider: str | None = None,
                    api_key: str | None = None,
                    base_url: str | None = None):
    """Create a provider instance.

    Args:
        model: Model name (used to auto-detect provider if not specified).
        provider: "anthropic" or "openai". Auto-detected if None.
        api_key: API key. Falls back to ANTHROPIC_API_KEY or OPENAI_API_KEY env vars.
        base_url: Custom endpoint URL. Forces OpenAI-compatible provider.
    """
    if base_url:
        # Custom endpoint → always OpenAI-compatible
        return OpenAIProvider(api_key=api_key, base_url=base_url)

    if provider is None:
        provider = detect_provider(model)

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    else:
        return OpenAIProvider(api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                              base_url=base_url)
