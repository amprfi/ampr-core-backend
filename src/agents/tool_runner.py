"""
Shared streaming-native Mistral tool runner.

This module provides a reusable tool runner that replaces the tool-loop behavior
currently provided by pydantic-ai for migrated agents. The runner is designed to be:

- Streaming-native: run_stream() is the primary execution path
- Generic: works with any Mistral model that supports tools and reasoning
- Safe: state is local to each invocation, safe for concurrent multi-module synthesis
- Resilient: validation failures and tool exceptions are fed back as tool results

The runner follows the design from the Linear document "Migration: Pydantic-AI →
Mistral SDK (reasoning, streaming, tools)" §4.6.

Key design decisions:
1. Schema generation via Pydantic args models (Decision 1)
2. Deps injection via closure factory (Decision 2)
3. Feed tool errors back, don't abort (Decision 3)
4. Discard thinking chunks always; never surface to UI (Decision 4)
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union, AsyncIterator

from pydantic import BaseModel, ValidationError
from mistralai.client import Mistral
from mistralai.client.models import (
    SystemMessage,
    UserMessage,
    ToolMessage,
    AssistantMessage,
    ToolCall,
    FunctionCall,
)
from mistralai.client.types import UNSET

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration and Types
# =============================================================================

@dataclass
class Tool:
    """
    A tool definition for the Mistral tool runner.

    Attributes:
        name: The tool name (used in function calling)
        description: The tool description (shown to the model)
        args_model: Pydantic BaseModel for argument validation and schema generation
        func: Async callable that executes the tool. Must accept **kwargs matching
             args_model fields and return a string or object that can be stringified.
    """
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[..., Any]


@dataclass
class RunnerConfig:
    """
    Configuration for the Mistral tool runner.

    Attributes:
        client: Mistral SDK client instance
        model: Model identifier (e.g., "mistral-medium-3-5")
        tools: Dictionary mapping tool names to Tool instances
        system_prompt: System prompt for the agent
        max_iterations: Maximum number of tool loop iterations (default: 10)
        reasoning_effort: "high" or "none" (default: "high")
        tool_choice: "auto", "required", or "none" (default: "auto")
    """
    client: Mistral
    model: str
    tools: dict[str, Tool]
    system_prompt: str
    max_iterations: int = 10
    reasoning_effort: str = "high"
    tool_choice: str = "auto"


@dataclass
class _CallResult:
    """
    Result of a single model call in the tool loop.

    Attributes:
        assistant_message: Full assistant message (AssistantMessage instance) for history coherence
        tool_calls: List of tool call dicts with id, name, args (for internal processing)
        finish_reason: The finish reason from the model
        text: Accumulated visible text (thinking chunks excluded); retained for direct
             _stream_one_call testability even though run_stream yields deltas live
    """
    assistant_message: AssistantMessage
    tool_calls: list[dict]
    finish_reason: Optional[str]
    text: str


@dataclass
class _StreamOutcome:
    """Holder for the _CallResult returned by _stream_one_call after streaming completes."""
    result: Optional[_CallResult] = None


# =============================================================================
# Finish Reason Mapping
# =============================================================================

_FINISH_REASON_MAP = {
    'stop': 'stop',
    'length': 'length',
    'model_length': 'length',
    'error': 'error',
    'tool_calls': 'tool_call'
}


def _is_terminal(finish_reason: Optional[str]) -> bool:
    """
    Check if a finish reason means the turn is terminal.

    Terminal reasons: stop, length, model_length, error
    Non-terminal: tool_calls (requires tool execution and another turn)
    Unknown reasons are treated as terminal for safety.
    """
    if finish_reason is None:
        return False
    mapped = _FINISH_REASON_MAP.get(finish_reason)
    # Unknown reasons (not in map) are treated as terminal for safety
    return True if mapped is None else mapped in ('stop', 'length', 'error')


# =============================================================================
# Schema Generation
# =============================================================================

def _generate_tool_schema(tool: Tool) -> dict[str, Any]:
    """
    Generate Mistral-compatible function tool schema from a Pydantic args model.

    Uses model.model_json_schema() to get the JSON schema, which Mistral's
    tools[].function.parameters accepts directly.

    Args:
        tool: The Tool instance with args_model

    Returns:
        Mistral function tool schema dict
    """
    schema = tool.args_model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        }
    }


def _to_mistral_tools(tools: dict[str, Tool]) -> list[dict[str, Any]]:
    """
    Convert a dictionary of Tool instances to Mistral function tool schemas.

    Args:
        tools: Dictionary mapping tool names to Tool instances

    Returns:
        List of Mistral function tool schema dicts
    """
    return [_generate_tool_schema(tool) for tool in tools.values()]


# =============================================================================
# Content Parsing
# =============================================================================

def _map_content(content: Any) -> tuple[str, str]:
    """
    Parse Mistral's shape-shifting delta.content during reasoning.

    When reasoning_effort="high", content can be:
    - None: no content
    - str: plain text (answer phase or reasoning off)
    - list: list of chunks (thinking phase or transition)
      - ThinkChunk: {"type": "thinking", "thinking": [{"type": "text", "text": "..."}]}
      - TextChunk: {"type": "text", "text": "..."}

    The Mistral SDK may return Pydantic model instances (ThinkChunk, TextChunk)
    or raw dicts, so we handle both.

    Returns:
        Tuple of (text: str, thinking: str) - the extracted text and thinking content
    """
    if content is None:
        return "", ""

    if isinstance(content, str):
        # Plain string content (reasoning_effort="none" or answer phase)
        return content, ""

    if isinstance(content, list):
        # List of chunks (reasoning_effort="high")
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        for chunk in content:
            # Handle both Pydantic model instances and raw dicts
            if hasattr(chunk, 'type'):
                # Pydantic model instance
                chunk_type = chunk.type
            elif isinstance(chunk, dict):
                chunk_type = chunk.get("type")
            else:
                continue

            if chunk_type == "text":
                # TextChunk: extract the text
                if hasattr(chunk, 'text'):
                    text_parts.append(chunk.text or "")
                elif isinstance(chunk, dict):
                    text_parts.append(chunk.get("text", ""))
            elif chunk_type == "thinking":
                # ThinkChunk: extract thinking content
                if hasattr(chunk, 'thinking'):
                    thinking_list = chunk.thinking or []
                elif isinstance(chunk, dict):
                    thinking_list = chunk.get("thinking", [])
                else:
                    thinking_list = []

                for t in thinking_list:
                    # Each thinking item can be a TextChunk model or dict
                    if hasattr(t, 'type') and hasattr(t, 'text'):
                        if t.type == "text":
                            thinking_parts.append(t.text or "")
                    elif isinstance(t, dict) and t.get("type") == "text":
                        thinking_parts.append(t.get("text", ""))

        return "".join(text_parts), "".join(thinking_parts)

    # Fallback: try to convert to string
    return str(content), ""


def _reconstruct_full_content(text_parts: list[str], thinking_parts: list[str]) -> Any:
    """
    Reconstruct the full assistant message content for history coherence.

    When reasoning_effort="high", the full content should include both thinking
    and text chunks for multi-turn coherence. When reasoning_effort="none",
    it's just the text.

    Args:
        text_parts: List of text chunk strings
        thinking_parts: List of thinking chunk strings

    Returns:
        Full content as a list of chunks (if thinking present) or string
    """
    text = "".join(text_parts)
    thinking = "".join(thinking_parts)

    if thinking:
        # reasoning_effort="high": return as list of chunks
        chunks = []
        if thinking:
            chunks.append({"type": "thinking", "thinking": [{"type": "text", "text": thinking}]})
        if text:
            chunks.append({"type": "text", "text": text})
        return chunks if chunks else ""
    elif text:
        # No thinking, but has text: return as plain string
        return text
    else:
        # No thinking, no text: return empty string
        return ""


# =============================================================================
# Tool Execution
# =============================================================================

async def _exec_tool(config: RunnerConfig, tool_call: dict) -> ToolMessage:
    """
    Execute a single tool call with argument validation.

    This function:
    1. Looks up the tool by name
    2. Validates arguments using the Pydantic args_model
    3. Executes the tool function
    4. Returns a ToolMessage for the conversation history

    All errors (unknown tool, invalid JSON, validation failure, execution error)
    are returned as tool-result messages rather than aborting the run.

    Args:
        config: Runner configuration with tools dictionary
        tool_call: Tool call dict with id, name, args fields

    Returns:
        ToolMessage instance for the conversation history
    """
    tool_name = tool_call.get("name", "")
    args_str = tool_call.get("args", "")
    tool_call_id = tool_call.get("id", "")

    try:
        # Get the tool
        tool = config.tools.get(tool_name)
        if tool is None:
            logger.warning(f"Unknown tool called: {tool_name}")
            return ToolMessage(
                role="tool",
                content=f"ERROR: Unknown tool '{tool_name}'",
                tool_call_id=tool_call_id,
                name=tool_name
            )

        # Validate arguments with Pydantic
        try:
            args_data = json.loads(args_str) if args_str else {}
            validated_args = tool.args_model(**args_data)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON arguments for tool {tool_name}: {e}")
            return ToolMessage(
                role="tool",
                content=f"ERROR: Invalid JSON arguments: {str(e)}",
                tool_call_id=tool_call_id,
                name=tool_name
            )
        except ValidationError as e:
            logger.warning(f"Validation error for tool {tool_name}: {e}")
            # Format validation errors nicely
            error_messages = []
            for err in e.errors():
                loc = " -> ".join(str(x) for x in err["loc"])
                msg = err["msg"]
                error_messages.append(f"{loc}: {msg}" if loc else msg)
            error_str = "; ".join(error_messages)
            return ToolMessage(
                role="tool",
                content=f"ERROR: Invalid arguments - {error_str}",
                tool_call_id=tool_call_id,
                name=tool_name
            )

        # Execute the tool
        try:
            result = await tool.func(**validated_args.model_dump())

            # Ensure result is string
            if result is None:
                result = ""
            elif not isinstance(result, str):
                result = str(result)

            return ToolMessage(
                role="tool",
                content=result,
                tool_call_id=tool_call_id,
                name=tool_name
            )

        except Exception as e:
            logger.error(f"Tool execution error for {tool_name}: {e}", exc_info=True)
            return ToolMessage(
                role="tool",
                content=f"ERROR: Tool execution failed - {str(e)}",
                tool_call_id=tool_call_id,
                name=tool_name
            )

    except Exception as e:
        logger.error(f"Unexpected error executing tool {tool_name}: {e}", exc_info=True)
        return ToolMessage(
            role="tool",
            content=f"ERROR: Unexpected error in tool '{tool_name}': {str(e)}",
            tool_call_id=tool_call_id,
            name=tool_name
        )


# =============================================================================
# Stream One Call
# =============================================================================

async def _stream_one_call(
    config: RunnerConfig,
    messages: list[Union[SystemMessage, UserMessage, ToolMessage, AssistantMessage]],
    outcome: _StreamOutcome
) -> AsyncIterator[str]:
    """
    Execute one model call and stream visible text deltas to the caller.

    This is the core of the tool loop. It:
    - Streams the model response
    - Yields visible text deltas (thinking chunks are NEVER yielded)
    - Parses content (text and thinking chunks)
    - Accumulates tool calls (Mistral sends them complete, not fragmented)
    - Tracks the finish reason
    - Stores the complete _CallResult in `outcome.result` for history/control flow

    Args:
        config: Runner configuration
        messages: Current conversation history
        outcome: Holder to receive the _CallResult after streaming completes

    Yields:
        Visible text deltas (str) as they arrive from the model stream.
        Thinking chunks are consumed internally and never yielded.
    """
    text_buf: list[str] = []
    thinking_buf: list[str] = []
    tool_calls: dict[int, dict] = {}  # index -> {id, name, args}
    finish_reason: Optional[str] = None

    # Convert tools to Mistral format
    mistral_tools = _to_mistral_tools(config.tools) if config.tools else None

    # Determine tool_choice: if tools are empty or tool_choice is "none", omit tools entirely
    # Per design doc §4.6: "none→omit tools entirely"
    if config.tool_choice == "none" or not mistral_tools:
        effective_tool_choice = None
        mistral_tools = UNSET
    else:
        effective_tool_choice = config.tool_choice

    async for event in await config.client.chat.stream_async(
        model=config.model,
        messages=messages,
        tools=mistral_tools,
        tool_choice=effective_tool_choice,
        reasoning_effort=config.reasoning_effort,
    ):
        choice = event.data.choices[0]

        # Update finish reason
        if choice.finish_reason:
            finish_reason = choice.finish_reason

        # Parse delta content (guard against None)
        delta_content = choice.delta.content if choice.delta else None
        text_delta, thinking_delta = _map_content(delta_content)
        thinking_buf.append(thinking_delta)
        if text_delta:
            text_buf.append(text_delta)
            yield text_delta  # Stream visible text deltas live to caller

        # Handle tool calls (Mistral sends them complete)
        if choice.delta and choice.delta.tool_calls:
            for tc in choice.delta.tool_calls:
                # Get index, defaulting to next available if None
                idx = tc.index if tc.index is not None else len(tool_calls)
                if idx not in tool_calls:
                    # Handle both Pydantic models and dicts
                    if hasattr(tc, 'id'):
                        tc_id = tc.id or ""
                    else:
                        tc_id = tc.get("id", "")

                    if hasattr(tc, 'function') and hasattr(tc.function, 'name'):
                        tc_name = tc.function.name
                    elif isinstance(tc, dict) and 'function' in tc:
                        tc_name = tc['function'].get('name', '') if isinstance(tc['function'], dict) else ''
                    else:
                        tc_name = ''

                    tool_calls[idx] = {
                        "id": tc_id,
                        "name": tc_name,
                        "args": ""
                    }

                # Get arguments - handle both Pydantic models and dicts
                if hasattr(tc, 'function') and hasattr(tc.function, 'arguments'):
                    args = tc.function.arguments or ""
                elif isinstance(tc, dict) and 'function' in tc:
                    args = tc['function'].get('arguments', '') or ''
                else:
                    args = ""

                # Mistral sends complete tool calls, so this is typically a no-op
                # (args arrive complete), but we append just in case
                tool_calls[idx]["args"] += args

    # Build full assistant message for history coherence
    full_content = _reconstruct_full_content(text_buf, thinking_buf)

    # Build tool_calls as proper ToolCall objects for history
    # Convert our accumulated dict tool_calls to proper ToolCall instances
    tool_call_objects = []
    for tc_dict in tool_calls.values():
        tool_call_objects.append(
            ToolCall(
                id=tc_dict["id"],
                function=FunctionCall(
                    name=tc_dict["name"],
                    arguments=tc_dict["args"]
                ),
                type="function"
            )
        )

    # Only omit content when it's empty AND there are tool calls (canonical tool-call shape)
    content = full_content if (full_content != "" or not tool_call_objects) else UNSET

    outcome.result = _CallResult(
        assistant_message=AssistantMessage(
            content=content,
            tool_calls=tool_call_objects if tool_call_objects else UNSET
        ),
        tool_calls=[{"id": tc.id, "name": tc.function.name, "args": tc.function.arguments}
                    for tc in tool_call_objects],
        finish_reason=finish_reason,
        text="".join(text_buf)
    )


# =============================================================================
# Main Runner Functions
# =============================================================================

async def run_stream(
    config: RunnerConfig,
    user_message: str
) -> AsyncIterator[str]:
    """
    Primary execution path: streaming tool loop.

    This is the single source of truth for execution. It:
    - Builds the initial conversation with system prompt and user message
    - Executes the model in a loop until a terminal finish reason
    - Yields only text deltas (thinking chunks are never yielded)
    - Executes tools when tool_calls are returned
    - Handles max_iterations protection

    Each invocation is stateless and safe for concurrent execution.
    The messages list is local to this function call.

    Args:
        config: Runner configuration
        user_message: The user's message to start the conversation

    Yields:
        Text deltas (thinking chunks are consumed internally, never yielded)
    """

    # Build initial messages - local to this invocation
    messages: list[Union[SystemMessage, UserMessage, ToolMessage, AssistantMessage]] = [
        SystemMessage(content=config.system_prompt),
        UserMessage(content=user_message)
    ]

    for iteration in range(config.max_iterations):
        # Execute one model call - yields visible text deltas live
        outcome = _StreamOutcome()
        async for delta in _stream_one_call(config, messages, outcome):
            # Stream visible text deltas to caller as they arrive
            yield delta

        # After streaming completes, get the result for control flow
        result = outcome.result

        # Add assistant message to history (full message for coherence)
        messages.append(result.assistant_message)

        # Check if this is a terminal state
        if _is_terminal(result.finish_reason):
            # Text already streamed live - just return
            return

        # Non-terminal with tool calls: execute tools
        if result.tool_calls:
            # Execute all tool calls concurrently
            # Ensure tool_calls is a list
            tool_call_list = result.tool_calls if isinstance(result.tool_calls, list) else []
            if tool_call_list:
                tool_messages = await asyncio.gather(
                    *[_exec_tool(config, tc) for tc in tool_call_list]
                )
                messages.extend(tool_messages)
            continue

        # Non-terminal without tool calls: text already streamed, just return
        # This can happen with finish_reason=None but no tool_calls
        return

    # Max iterations reached
    yield "[max tool iterations reached]"


async def run(
    config: RunnerConfig,
    user_message: str
) -> str:
    """
    Non-streaming execution: joins the streamed results.

    This is simply a convenience wrapper that joins all text deltas
    from run_stream(). Useful for background agents that don't need streaming.

    Args:
        config: Runner configuration
        user_message: The user's message

    Returns:
        Complete response text as a single string
    """
    return "".join([chunk async for chunk in run_stream(config, user_message)])


# =============================================================================
# Tool Factory Helper
# =============================================================================

def create_tool(
    name: str,
    description: str,
    args_model: type[BaseModel]
) -> Callable:
    """
    Decorator to create a Tool instance from a function.

    This decorator REPLACES the decorated function with a Tool instance.
    The decorated name will be a Tool object, not the original function.

    Usage:
        class GetUserCountryArgs(BaseModel):
            user_id: str = Field(description="The user ID")

        # After decoration, get_user_country_tool is a Tool instance
        @create_tool("get_user_country", "Get user's country", GetUserCountryArgs)
        async def get_user_country_tool(user_id: str) -> str:
            # Tool implementation
            return country

        # Use it in RunnerConfig:
        config = RunnerConfig(
            tools={"get_user_country": get_user_country_tool},
            ...
        )

    Note: The decorated function should accept **kwargs matching the args_model
    fields. The original function is stored in the Tool instance's .func attribute.

    Args:
        name: Tool name
        description: Tool description
        args_model: Pydantic BaseModel for argument validation

    Returns:
        Decorator function that returns a Tool instance (not the original function)
    """
    def decorator(func: Callable) -> Tool:
        return Tool(
            name=name,
            description=description,
            args_model=args_model,
            func=func
        )
    return decorator


# =============================================================================
# Convenience: Pre-built Tool Registry
# =============================================================================

class ToolRegistry:
    """
    Convenience class for building a tools dictionary from decorated functions.

    Usage:
        registry = ToolRegistry()

        @registry.tool("get_country", "Get country", GetCountryArgs)
        async def get_country_tool(**kwargs):
            ...

        config = RunnerConfig(
            client=client,
            model="mistral-medium-3-5",
            tools=registry.build(),
            system_prompt="..."
        )
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def tool(
        self,
        name: str,
        description: str,
        args_model: type[BaseModel]
    ) -> Callable:
        """
        Decorator to register a tool function.

        This decorator registers the tool in the registry and returns the ORIGINAL
        function (not a Tool instance), allowing for decorator chaining.

        To get the Tool instances, call registry.build() after defining all tools.

        Usage:
            registry = ToolRegistry()

            # The decorated function remains a function (for chaining)
            @registry.tool("get_country", "Get country", GetCountryArgs)
            async def get_country_tool(**kwargs):
                ...

            # Build the tools dict for RunnerConfig
            config = RunnerConfig(
                tools=registry.build(),  # Returns dict[str, Tool]
                ...
            )

        Args:
            name: Tool name
            description: Tool description
            args_model: Pydantic BaseModel for argument validation

        Returns:
            Decorator that registers the tool and returns the ORIGINAL function
            (not a Tool instance - use registry.build() to get Tool instances)
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = Tool(
                name=name,
                description=description,
                args_model=args_model,
                func=func
            )
            return func
        return decorator

    def add(self, tool: Tool) -> None:
        """Add a pre-constructed Tool to the registry."""
        self._tools[tool.name] = tool

    def build(self) -> dict[str, Tool]:
        """Build the tools dictionary."""
        return self._tools.copy()

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
