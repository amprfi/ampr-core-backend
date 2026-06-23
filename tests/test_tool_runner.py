"""
Tests for the shared streaming-native Mistral tool runner (AMPRFI-116).

Focused tests covering:
- Parsing (content parsing, reasoning chunks)
- Validation failures (Pydantic validation, JSON parsing)
- Tool errors (execution errors, unknown tools)
- Finish reasons (stop, tool_calls, length, error)
- State isolation (concurrent invocations)
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Any, AsyncIterator
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError
from mistralai.client.models import (
    SystemMessage,
    UserMessage,
    ToolMessage,
    AssistantMessage,
    CompletionEvent,
    CompletionChunk,
    CompletionResponseStreamChoice,
    DeltaMessage,
)

from src.agents.tool_runner import (
    Tool,
    RunnerConfig,
    run_stream,
    run,
    _CallResult,
    _StreamOutcome,
    _map_content,
    _reconstruct_full_content,
    _is_terminal,
    _generate_tool_schema,
    _to_mistral_tools,
    _exec_tool,
    _stream_one_call,
    create_tool,
    ToolRegistry,
    _FINISH_REASON_MAP,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_mistral_client():
    """Create a mocked Mistral client."""
    client = MagicMock()
    client.chat.stream_async = AsyncMock()
    return client


@pytest.fixture
def mock_tool_args_model():
    """Create a simple Pydantic model for tool arguments."""
    class SimpleArgs(BaseModel):
        name: str = Field(description="A name")
        value: int = Field(description="A value")
    return SimpleArgs


@pytest.fixture
def mock_tool():
    """Create a mock Tool instance."""
    class SimpleArgs(BaseModel):
        name: str = Field(description="A name")
    
    async def simple_func(name: str) -> str:
        return f"Hello, {name}!"
    
    return Tool(
        name="simple_tool",
        description="A simple test tool",
        args_model=SimpleArgs,
        func=simple_func
    )


@pytest.fixture
def mock_runner_config(mock_mistral_client, mock_tool):
    """Create a RunnerConfig with mocked components."""
    return RunnerConfig(
        client=mock_mistral_client,
        model="mistral-medium-3-5",
        tools={"simple_tool": mock_tool},
        system_prompt="You are a helpful assistant.",
        max_iterations=5,
        reasoning_effort="high",
        tool_choice="auto"
    )


# =============================================================================
# Test Content Parsing (_map_content)
# =============================================================================

class TestMapContent:
    """Tests for _map_content helper function."""
    
    def test_none_content(self):
        """Test that None content returns empty strings."""
        text, thinking = _map_content(None)
        assert text == ""
        assert thinking == ""
    
    def test_plain_string(self):
        """Test that plain string content is returned as text."""
        text, thinking = _map_content("Hello, world!")
        assert text == "Hello, world!"
        assert thinking == ""
    
    def test_empty_string(self):
        """Test that empty string returns empty strings."""
        text, thinking = _map_content("")
        assert text == ""
        assert thinking == ""
    
    def test_text_chunk_only(self):
        """Test parsing a list with only TextChunk."""
        content = [{"type": "text", "text": "Hello"}]
        text, thinking = _map_content(content)
        assert text == "Hello"
        assert thinking == ""
    
    def test_thinking_chunk_only(self):
        """Test parsing a list with only ThinkChunk."""
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Let me think..."}]}
        ]
        text, thinking = _map_content(content)
        assert text == ""
        assert thinking == "Let me think..."
    
    def test_mixed_chunks(self):
        """Test parsing a list with both TextChunk and ThinkChunk."""
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Thinking..."}]},
            {"type": "text", "text": "Hello"},
            {"type": "thinking", "thinking": [{"type": "text", "text": "More thinking"}]},
            {"type": "text", "text": "World"},
        ]
        text, thinking = _map_content(content)
        assert text == "HelloWorld"
        assert thinking == "Thinking...More thinking"
    
    def test_nested_thinking_chunk(self):
        """Test parsing ThinkChunk with nested text chunks."""
        content = [
            {
                "type": "thinking",
                "thinking": [
                    {"type": "text", "text": "First thought"},
                    {"type": "text", "text": "Second thought"}
                ]
            }
        ]
        text, thinking = _map_content(content)
        assert text == ""
        assert thinking == "First thoughtSecond thought"
    
    def test_empty_list(self):
        """Test that empty list returns empty strings."""
        text, thinking = _map_content([])
        assert text == ""
        assert thinking == ""
    
    def test_non_dict_items_ignored(self):
        """Test that non-dict items in list are ignored."""
        content = ["not a dict", {"type": "text", "text": "Hello"}, 123]
        text, thinking = _map_content(content)
        assert text == "Hello"
        assert thinking == ""
    
    def test_missing_type_field(self):
        """Test that chunks without type field are ignored."""
        content = [{"text": "Hello"}, {"type": "text", "text": "World"}]
        text, thinking = _map_content(content)
        assert text == "World"
        assert thinking == ""
    
    def test_unknown_chunk_type(self):
        """Test that unknown chunk types are ignored."""
        content = [{"type": "unknown", "text": "Hello"}, {"type": "text", "text": "World"}]
        text, thinking = _map_content(content)
        assert text == "World"
        assert thinking == ""
    
    def test_fallback_to_string(self):
        """Test that non-string, non-list content falls back to string conversion."""
        text, thinking = _map_content(12345)
        assert text == "12345"
        assert thinking == ""


# =============================================================================
# Test Full Content Reconstruction
# =============================================================================

class TestReconstructFullContent:
    """Tests for _reconstruct_full_content helper."""
    
    def test_text_only(self):
        """Test reconstruction with only text parts."""
        result = _reconstruct_full_content(["Hello", "World"], [])
        assert result == "HelloWorld"
    
    def test_thinking_only(self):
        """Test reconstruction with only thinking parts."""
        result = _reconstruct_full_content([], ["Thinking...", "More"])
        assert result == [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Thinking...More"}]}
        ]
    
    def test_both_text_and_thinking(self):
        """Test reconstruction with both text and thinking parts."""
        result = _reconstruct_full_content(["Hello"], ["Thinking"])
        assert result == [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Thinking"}]},
            {"type": "text", "text": "Hello"}
        ]
    
    def test_empty_parts(self):
        """Test reconstruction with empty parts."""
        result = _reconstruct_full_content([], [])
        assert result == ""


# =============================================================================
# Test Finish Reason Mapping
# =============================================================================

class TestIsTerminal:
    """Tests for _is_terminal and finish reason mapping."""
    
    def test_stop_is_terminal(self):
        """Test that 'stop' finish reason is terminal."""
        assert _is_terminal("stop") is True
    
    def test_length_is_terminal(self):
        """Test that 'length' finish reason is terminal."""
        assert _is_terminal("length") is True
    
    def test_model_length_is_terminal(self):
        """Test that 'model_length' finish reason is terminal."""
        assert _is_terminal("model_length") is True
    
    def test_error_is_terminal(self):
        """Test that 'error' finish reason is terminal."""
        assert _is_terminal("error") is True
    
    def test_tool_calls_is_not_terminal(self):
        """Test that 'tool_calls' finish reason is NOT terminal."""
        assert _is_terminal("tool_calls") is False
    
    def test_none_is_not_terminal(self):
        """Test that None finish reason is NOT terminal."""
        assert _is_terminal(None) is False
    
    def test_unknown_reason_is_terminal(self):
        """Test that unknown finish reasons are treated as terminal."""
        assert _is_terminal("unknown") is True
    
    def test_finish_reason_map_completeness(self):
        """Test that the finish reason map covers expected values."""
        expected = {
            'stop': 'stop',
            'length': 'length',
            'model_length': 'length',
            'error': 'error',
            'tool_calls': 'tool_call'
        }
        assert _FINISH_REASON_MAP == expected


# =============================================================================
# Test Schema Generation
# =============================================================================

class TestSchemaGeneration:
    """Tests for schema generation from Pydantic models."""
    
    def test_simple_model_schema(self, mock_tool):
        """Test schema generation for a simple model."""
        schema = _generate_tool_schema(mock_tool)
        
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "simple_tool"
        assert schema["function"]["description"] == "A simple test tool"
        assert "properties" in schema["function"]["parameters"]
    
    def test_complex_model_schema(self):
        """Test schema generation for a complex nested model."""
        class Address(BaseModel):
            street: str
            city: str
        
        class Person(BaseModel):
            name: str = Field(description="Person's name")
            age: int = Field(description="Person's age")
            address: Address = Field(description="Person's address")
        
        tool = Tool(
            name="create_person",
            description="Create a person",
            args_model=Person,
            func=lambda **kwargs: "ok"
        )
        
        schema = _generate_tool_schema(tool)
        
        assert schema["function"]["name"] == "create_person"
        params = schema["function"]["parameters"]
        assert "name" in params["properties"]
        assert "age" in params["properties"]
        assert "address" in params["properties"]
        assert params["properties"]["name"]["description"] == "Person's name"
    
    def test_tools_list_generation(self):
        """Test _to_mistral_tools with multiple tools."""
        class Args1(BaseModel):
            x: int
        
        class Args2(BaseModel):
            y: str
        
        tools = {
            "tool1": Tool(name="tool1", description="Tool 1", args_model=Args1, func=lambda **kw: "ok"),
            "tool2": Tool(name="tool2", description="Tool 2", args_model=Args2, func=lambda **kw: "ok"),
        }
        
        mistral_tools = _to_mistral_tools(tools)
        
        assert len(mistral_tools) == 2
        assert mistral_tools[0]["function"]["name"] == "tool1"
        assert mistral_tools[1]["function"]["name"] == "tool2"
    
    def test_empty_tools_list(self):
        """Test _to_mistral_tools with empty dict."""
        mistral_tools = _to_mistral_tools({})
        assert mistral_tools == []


# =============================================================================
# Test Tool Execution
# =============================================================================

class TestExecTool:
    """Tests for _exec_tool function."""
    
    @pytest.mark.asyncio
    async def test_successful_tool_execution(self, mock_runner_config):
        """Test successful tool execution with valid arguments."""
        tool_call = {
            "id": "call_123",
            "name": "simple_tool",
            "args": '{"name": "Test"}'
        }
        
        result = await _exec_tool(mock_runner_config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert result.role == "tool"
        assert result.name == "simple_tool"
        assert result.tool_call_id == "call_123"
        assert "Hello, Test!" in result.content
    
    @pytest.mark.asyncio
    async def test_unknown_tool(self, mock_runner_config):
        """Test that unknown tool returns error message."""
        tool_call = {
            "id": "call_123",
            "name": "nonexistent_tool",
            "args": '{}'
        }
        
        result = await _exec_tool(mock_runner_config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert "ERROR: Unknown tool" in result.content
        assert result.name == "nonexistent_tool"
    
    @pytest.mark.asyncio
    async def test_invalid_json_args(self, mock_runner_config):
        """Test that invalid JSON arguments return error message."""
        tool_call = {
            "id": "call_123",
            "name": "simple_tool",
            "args": "not valid json"
        }
        
        result = await _exec_tool(mock_runner_config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert "ERROR: Invalid JSON arguments" in result.content
    
    @pytest.mark.asyncio
    async def test_validation_error(self, mock_runner_config):
        """Test that Pydantic validation errors return error message."""
        # The simple_tool expects a 'name' field (required)
        tool_call = {
            "id": "call_123",
            "name": "simple_tool",
            "args": '{"value": 42}'  # Missing required 'name' field
        }
        
        result = await _exec_tool(mock_runner_config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert "ERROR: Invalid arguments" in result.content
    
    @pytest.mark.asyncio
    async def test_tool_execution_error(self, mock_runner_config):
        """Test that tool execution errors return error message."""
        # Create a tool that raises an exception
        class ErrorArgs(BaseModel):
            should_fail: bool = False
        
        async def failing_tool(should_fail: bool) -> str:
            if should_fail:
                raise ValueError("Intentional error")
            return "ok"
        
        error_tool = Tool(
            name="failing_tool",
            description="A tool that fails",
            args_model=ErrorArgs,
            func=failing_tool
        )
        
        config = RunnerConfig(
            client=mock_runner_config.client,
            model=mock_runner_config.model,
            tools={"failing_tool": error_tool},
            system_prompt=mock_runner_config.system_prompt
        )
        
        tool_call = {
            "id": "call_123",
            "name": "failing_tool",
            "args": '{"should_fail": true}'
        }
        
        result = await _exec_tool(config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert "ERROR: Tool execution failed" in result.content
    
    @pytest.mark.asyncio
    async def test_tool_returns_non_string(self, mock_runner_config):
        """Test that tool returning non-string is converted to string."""
        class SimpleArgs(BaseModel):
            value: int
        
        async def returns_dict(value: int) -> dict:
            return {"result": value * 2}
        
        dict_tool = Tool(
            name="dict_tool",
            description="Returns a dict",
            args_model=SimpleArgs,
            func=returns_dict
        )
        
        config = RunnerConfig(
            client=mock_runner_config.client,
            model=mock_runner_config.model,
            tools={"dict_tool": dict_tool},
            system_prompt=mock_runner_config.system_prompt
        )
        
        tool_call = {
            "id": "call_123",
            "name": "dict_tool",
            "args": '{"value": 5}'
        }
        
        result = await _exec_tool(config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert isinstance(result.content, str)
        assert "result" in result.content
    
    @pytest.mark.asyncio
    async def test_tool_returns_none(self, mock_runner_config):
        """Test that tool returning None is converted to empty string."""
        class SimpleArgs(BaseModel):
            pass
        
        async def returns_none(**kwargs) -> None:
            return None
        
        none_tool = Tool(
            name="none_tool",
            description="Returns None",
            args_model=SimpleArgs,
            func=returns_none
        )
        
        config = RunnerConfig(
            client=mock_runner_config.client,
            model=mock_runner_config.model,
            tools={"none_tool": none_tool},
            system_prompt=mock_runner_config.system_prompt
        )
        
        tool_call = {
            "id": "call_123",
            "name": "none_tool",
            "args": '{}'
        }
        
        result = await _exec_tool(config, tool_call)
        
        assert isinstance(result, ToolMessage)
        assert result.content == ""


# =============================================================================
# Test Stream One Call
# =============================================================================

class TestStreamOneCall:
    """Tests for _stream_one_call function."""
    
    @pytest.fixture
    def mock_stream_events(self):
        """Create mock stream events for testing."""
        events = []
        
        # Create a mock event with text delta
        event1 = MagicMock()
        event1.data = MagicMock()
        event1.data.choices = [MagicMock()]
        event1.data.choices[0].finish_reason = None
        event1.data.choices[0].delta = MagicMock()
        event1.data.choices[0].delta.content = "Hello"
        event1.data.choices[0].delta.tool_calls = None
        events.append(event1)
        
        # Create a mock event with finish_reason
        event2 = MagicMock()
        event2.data = MagicMock()
        event2.data.choices = [MagicMock()]
        event2.data.choices[0].finish_reason = "stop"
        event2.data.choices[0].delta = MagicMock()
        event2.data.choices[0].delta.content = "World"
        event2.data.choices[0].delta.tool_calls = None
        events.append(event2)
        
        return events
    
    @pytest.mark.asyncio
    async def test_stream_one_call_basic(self, mock_runner_config):
        """Test basic _stream_one_call execution."""
        from mistralai.client.models import (
            CompletionEvent,
            CompletionChunk,
            CompletionResponseStreamChoice,
            DeltaMessage,
        )
        
        events = []
        
        # First event with text
        delta1 = DeltaMessage(content="Hello")
        choice1 = CompletionResponseStreamChoice(
            index=0,
            delta=delta1,
            finish_reason=None
        )
        chunk1 = CompletionChunk(
            id="cmpl_1",
            model="mistral-medium-3-5",
            choices=[choice1],
            object="chat.completion.chunk"
        )
        event1 = CompletionEvent(data=chunk1)
        events.append(event1)
        
        # Second event with text and finish_reason
        delta2 = DeltaMessage(content="World")
        choice2 = CompletionResponseStreamChoice(
            index=0,
            delta=delta2,
            finish_reason="stop"
        )
        chunk2 = CompletionChunk(
            id="cmpl_2",
            model="mistral-medium-3-5",
            choices=[choice2],
            object="chat.completion.chunk"
        )
        event2 = CompletionEvent(data=chunk2)
        events.append(event2)
        
        async def mock_stream():
            for event in events:
                yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        from src.agents.tool_runner import _StreamOutcome
        
        messages = [
            SystemMessage(content="You are a helper"),
            UserMessage(content="Hello")
        ]
        
        outcome = _StreamOutcome()
        deltas = []
        async for delta in _stream_one_call(mock_runner_config, messages, outcome):
            deltas.append(delta)
        
        assert outcome.result is not None
        result = outcome.result
        assert isinstance(result, _CallResult)
        assert "".join(deltas) == "HelloWorld"
        assert result.text == "HelloWorld"
        assert result.finish_reason == "stop"
        assert result.tool_calls == []
    
    @pytest.mark.asyncio
    async def test_stream_one_call_with_tool_calls(self, mock_runner_config):
        """Test _stream_one_call with tool calls in the stream."""
        from mistralai.client.models import (
            CompletionEvent,
            CompletionChunk,
            CompletionResponseStreamChoice,
            DeltaMessage,
            ToolCall,
            FunctionCall,
        )
        
        events = []
        
        # Event with tool call
        tool_call = ToolCall(
            index=0,
            id="call_123",
            function=FunctionCall(name="simple_tool", arguments='{"name": "test"}'),
            type="function"
        )
        delta1 = DeltaMessage(content=None, tool_calls=[tool_call])
        choice1 = CompletionResponseStreamChoice(
            index=0,
            delta=delta1,
            finish_reason=None
        )
        chunk1 = CompletionChunk(
            id="cmpl_1",
            model="mistral-medium-3-5",
            choices=[choice1],
            object="chat.completion.chunk"
        )
        event1 = CompletionEvent(data=chunk1)
        events.append(event1)
        
        # Event with finish_reason
        delta2 = DeltaMessage(content=None, tool_calls=None)
        choice2 = CompletionResponseStreamChoice(
            index=0,
            delta=delta2,
            finish_reason="tool_calls"
        )
        chunk2 = CompletionChunk(
            id="cmpl_2",
            model="mistral-medium-3-5",
            choices=[choice2],
            object="chat.completion.chunk"
        )
        event2 = CompletionEvent(data=chunk2)
        events.append(event2)
        
        async def mock_stream():
            for event in events:
                yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        messages = [
            SystemMessage(content="You are a helper"),
            UserMessage(content="Call a tool")
        ]
        
        outcome = _StreamOutcome()
        deltas = []
        async for delta in _stream_one_call(mock_runner_config, messages, outcome):
            deltas.append(delta)
        
        assert outcome.result is not None
        result = outcome.result
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "simple_tool"
        assert result.tool_calls[0]["args"] == '{"name": "test"}'
        # No visible text deltas expected (tool call event has content=None)
        assert "".join(deltas) == ""
    
    @pytest.mark.asyncio
    async def test_stream_one_call_with_reasoning_chunks(self, mock_runner_config):
        """Test _stream_one_call with reasoning chunks (thinking content)."""
        from mistralai.client.models import (
            CompletionEvent,
            CompletionChunk,
            CompletionResponseStreamChoice,
            DeltaMessage,
        )
        
        events = []
        
        # Event with thinking chunk (as list)
        thinking_content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Let me think..."}]}
        ]
        delta1 = DeltaMessage(content=thinking_content, tool_calls=None)
        choice1 = CompletionResponseStreamChoice(
            index=0,
            delta=delta1,
            finish_reason=None
        )
        chunk1 = CompletionChunk(
            id="cmpl_1",
            model="mistral-medium-3-5",
            choices=[choice1],
            object="chat.completion.chunk"
        )
        event1 = CompletionEvent(data=chunk1)
        events.append(event1)
        
        # Event with text chunk
        delta2 = DeltaMessage(content="The answer is", tool_calls=None)
        choice2 = CompletionResponseStreamChoice(
            index=0,
            delta=delta2,
            finish_reason=None
        )
        chunk2 = CompletionChunk(
            id="cmpl_2",
            model="mistral-medium-3-5",
            choices=[choice2],
            object="chat.completion.chunk"
        )
        event2 = CompletionEvent(data=chunk2)
        events.append(event2)
        
        # Event with finish
        delta3 = DeltaMessage(content="42", tool_calls=None)
        choice3 = CompletionResponseStreamChoice(
            index=0,
            delta=delta3,
            finish_reason="stop"
        )
        chunk3 = CompletionChunk(
            id="cmpl_3",
            model="mistral-medium-3-5",
            choices=[choice3],
            object="chat.completion.chunk"
        )
        event3 = CompletionEvent(data=chunk3)
        events.append(event3)
        
        async def mock_stream():
            for event in events:
                yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        messages = [
            SystemMessage(content="You are a helper"),
            UserMessage(content="What is the answer?")
        ]
        
        outcome = _StreamOutcome()
        deltas = []
        async for delta in _stream_one_call(mock_runner_config, messages, outcome):
            deltas.append(delta)
        
        assert outcome.result is not None
        result = outcome.result
        # Text should contain only the text chunks, not thinking
        assert result.text == "The answer is42"
        assert "".join(deltas) == "The answer is42"
        # Full assistant message should include thinking for history
        assert isinstance(result.assistant_message.content, list)


# =============================================================================
# Test Main Runner Functions
# =============================================================================

class TestRunStream:
    """Tests for run_stream function."""
    
    @pytest.mark.asyncio
    async def test_run_stream_terminal_stop(self, mock_runner_config):
        """Test run_stream with terminal stop finish reason."""
        # Mock a single call that returns stop
        async def mock_stream():
            event = MagicMock()
            event.data = MagicMock()
            event.data.choices = [MagicMock()]
            event.data.choices[0].finish_reason = "stop"
            event.data.choices[0].delta = MagicMock()
            event.data.choices[0].delta.content = "Hello, world!"
            event.data.choices[0].delta.tool_calls = None
            yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "Hello"):
            chunks.append(chunk)
        
        assert len(chunks) == 1
        assert chunks[0] == "Hello, world!"
    
    @pytest.mark.asyncio
    async def test_run_stream_with_tool_loop(self, mock_runner_config):
        """Test run_stream with tool calls that trigger another turn."""
        call_count = 0
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            if call_count == 1:
                # First call: return tool_calls (no visible text - realistic for tool-only turns)
                tool_call = ToolCall(
                    index=0,
                    id="call_1",
                    function=FunctionCall(name="simple_tool", arguments='{"name": "test"}'),
                    type="function"
                )
                delta = DeltaMessage(content=None, tool_calls=[tool_call])
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="tool_calls"
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            else:
                # Second call: return stop
                delta = DeltaMessage(content="Done!")
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="stop"
                )
                chunk = CompletionChunk(
                    id="cmpl_2",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
        
        # Make stream_async return a new generator each time it's called
        mock_runner_config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "Hello"):
            chunks.append(chunk)
        
        # Should have made 2 calls (tool call + final answer)
        assert call_count == 2
        # Should yield the final answer
        assert len(chunks) == 1
        assert chunks[0] == "Done!"
    
    @pytest.mark.asyncio
    async def test_run_stream_max_iterations(self, mock_runner_config):
        """Test that run_stream respects max_iterations."""
        call_count = 0
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            tool_call = ToolCall(
                index=0,
                id=f"call_{call_count}",
                function=FunctionCall(name="simple_tool", arguments='{"name": "test"}'),
                type="function"
            )
            delta = DeltaMessage(content=None, tool_calls=[tool_call])
            choice = CompletionResponseStreamChoice(
                index=0,
                delta=delta,
                finish_reason="tool_calls"
            )
            chunk = CompletionChunk(
                id=f"cmpl_{call_count}",
                model="mistral-medium-3-5",
                choices=[choice],
                object="chat.completion.chunk"
            )
            event = CompletionEvent(data=chunk)
            yield event
        
        # Set max_iterations to 2
        config = RunnerConfig(
            client=mock_runner_config.client,
            model=mock_runner_config.model,
            tools=mock_runner_config.tools,
            system_prompt=mock_runner_config.system_prompt,
            max_iterations=2,
            reasoning_effort="high",
            tool_choice="auto"
        )
        
        # Make stream_async return a new generator each time it's called
        config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        chunks = []
        async for chunk in run_stream(config, "Hello"):
            chunks.append(chunk)
        
        # Should have stopped after 2 iterations
        assert call_count == 2
        # Should yield the max iterations message
        assert len(chunks) == 1
        assert "[max tool iterations reached]" in chunks[0]
    
    @pytest.mark.asyncio
    async def test_run_stream_length_finish(self, mock_runner_config):
        """Test run_stream with length finish reason."""
        async def mock_stream():
            event = MagicMock()
            event.data = MagicMock()
            event.data.choices = [MagicMock()]
            event.data.choices[0].finish_reason = "length"
            event.data.choices[0].delta = MagicMock()
            event.data.choices[0].delta.content = "Truncated response"
            event.data.choices[0].delta.tool_calls = None
            yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "Hello"):
            chunks.append(chunk)
        
        assert len(chunks) == 1
        assert chunks[0] == "Truncated response"

    @pytest.mark.asyncio
    async def test_run_stream_message_history_validation(self, mock_runner_config):
        """Test that message history sent to stream_async contains proper AssistantMessage with tool_calls."""
        call_count = 0
        messages_sent = []
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            if call_count == 1:
                # First call: return tool_calls
                tool_call = ToolCall(
                    index=0,
                    id="call_123",
                    function=FunctionCall(name="simple_tool", arguments='{"name": "test"}'),
                    type="function"
                )
                delta = DeltaMessage(content="I need to use a tool", tool_calls=[tool_call])
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="tool_calls"
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            else:
                # Second call: return stop
                delta = DeltaMessage(content="Done!")
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="stop"
                )
                chunk = CompletionChunk(
                    id="cmpl_2",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
        
        # Track messages sent to stream_async - capture a copy each time
        original_stream_async = mock_runner_config.client.chat.stream_async
        
        async def tracking_stream_async(*args, **kwargs):
            # Store a COPY of the messages list to avoid mutation issues
            messages_sent.append(list(kwargs.get("messages", [])))
            return make_stream()
        
        mock_runner_config.client.chat.stream_async = tracking_stream_async
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "Hello"):
            chunks.append(chunk)
        
        # Should have made 2 API calls
        assert call_count == 2
        
        # Validate first call messages (system + user only)
        assert len(messages_sent) == 2
        first_call_messages = messages_sent[0]
        assert len(first_call_messages) == 2
        assert isinstance(first_call_messages[0], SystemMessage)
        assert isinstance(first_call_messages[1], UserMessage)
        
        # Validate second call messages (system + user + assistant + tool)
        second_call_messages = messages_sent[1]
        assert len(second_call_messages) == 4
        
        # The third message (index 2) should be an AssistantMessage with tool_calls
        assistant_msg = second_call_messages[2]
        assert isinstance(assistant_msg, AssistantMessage)
        assert assistant_msg.role == "assistant"
        
        # Check that tool_calls are present and match the tool message
        assert assistant_msg.tool_calls is not None
        assert len(assistant_msg.tool_calls) == 1
        assert assistant_msg.tool_calls[0].id == "call_123"
        assert assistant_msg.tool_calls[0].function.name == "simple_tool"
        
        # The fourth message should be a ToolMessage with matching tool_call_id
        tool_msg = second_call_messages[3]
        assert isinstance(tool_msg, ToolMessage)
        assert tool_msg.tool_call_id == "call_123"
        assert tool_msg.name == "simple_tool"

    @pytest.mark.asyncio
    async def test_run_stream_yields_incremental_deltas(self, mock_runner_config):
        """Test that run_stream yields text deltas incrementally (true streaming)."""
        async def mock_stream():
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
            )
            # Multiple events with separate deltas
            for text in ["Hello", " ", "World", "!"]:
                delta = DeltaMessage(content=text)
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason=None
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            # Final event with finish
            delta = DeltaMessage(content="")
            choice = CompletionResponseStreamChoice(
                index=0,
                delta=delta,
                finish_reason="stop"
            )
            chunk = CompletionChunk(
                id="cmpl_2",
                model="mistral-medium-3-5",
                choices=[choice],
                object="chat.completion.chunk"
            )
            event = CompletionEvent(data=chunk)
            yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "Hello"):
            chunks.append(chunk)
        
        # Should have yielded each delta separately
        assert len(chunks) == 4
        assert chunks == ["Hello", " ", "World", "!"]

    @pytest.mark.asyncio
    async def test_run_stream_surfaces_tool_round_preamble(self, mock_runner_config):
        """Test that tool-round preamble text is streamed when present (b1 behavior)."""
        call_count = 0
        
        async def make_stream():
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            if call_count == 1:
                # Tool round with explicit preamble text
                tool_call = ToolCall(
                    index=0,
                    id="call_1",
                    function=FunctionCall(name="simple_tool", arguments='{"name": "test"}'),
                    type="function"
                )
                delta = DeltaMessage(content="Let me check...", tool_calls=[tool_call])
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="tool_calls"
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            else:
                # Final answer
                delta = DeltaMessage(content="The answer is 42")
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="stop"
                )
                chunk = CompletionChunk(
                    id="cmpl_2",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
        
        mock_runner_config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        chunks = []
        async for chunk in run_stream(mock_runner_config, "What is the answer?"):
            chunks.append(chunk)
        
        # Preamble from tool round + final answer should both be streamed
        assert len(chunks) == 2
        assert chunks[0] == "Let me check..."
        assert chunks[1] == "The answer is 42"


class TestRun:
    """Tests for run function (non-streaming)."""
    
    @pytest.mark.asyncio
    async def test_run_joins_stream(self, mock_runner_config):
        """Test that run() joins the streamed results."""
        async def mock_stream():
            event = MagicMock()
            event.data = MagicMock()
            event.data.choices = [MagicMock()]
            event.data.choices[0].finish_reason = "stop"
            event.data.choices[0].delta = MagicMock()
            event.data.choices[0].delta.content = "Hello, world!"
            event.data.choices[0].delta.tool_calls = None
            yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        result = await run(mock_runner_config, "Hello")
        
        assert result == "Hello, world!"
    
    @pytest.mark.asyncio
    async def test_run_empty_response(self, mock_runner_config):
        """Test run() with empty response."""
        async def mock_stream():
            event = MagicMock()
            event.data = MagicMock()
            event.data.choices = [MagicMock()]
            event.data.choices[0].finish_reason = "stop"
            event.data.choices[0].delta = MagicMock()
            event.data.choices[0].delta.content = ""
            event.data.choices[0].delta.tool_calls = None
            yield event
        
        mock_runner_config.client.chat.stream_async.return_value = mock_stream()
        
        result = await run(mock_runner_config, "Hello")
        
        assert result == ""


# =============================================================================
# Test Tool Factory
# =============================================================================

class TestCreateTool:
    """Tests for create_tool decorator."""
    
    def test_create_tool_decorator(self):
        """Test that create_tool creates a Tool instance."""
        class SimpleArgs(BaseModel):
            x: int
        
        @create_tool("test_tool", "A test tool", SimpleArgs)
        async def test_func(x: int) -> str:
            return str(x * 2)
        
        assert isinstance(test_func, Tool)
        assert test_func.name == "test_tool"
        assert test_func.description == "A test tool"
        assert test_func.args_model == SimpleArgs
        assert callable(test_func.func)


# =============================================================================
# Test Tool Registry
# =============================================================================

class TestToolRegistry:
    """Tests for ToolRegistry class."""
    
    def test_registry_add_tool(self):
        """Test adding a tool to the registry."""
        registry = ToolRegistry()
        
        class SimpleArgs(BaseModel):
            x: int
        
        @registry.tool("tool1", "Tool 1", SimpleArgs)
        async def tool1(x: int) -> str:
            return str(x)
        
        tools = registry.build()
        
        assert "tool1" in tools
        assert tools["tool1"].name == "tool1"
    
    def test_registry_multiple_tools(self):
        """Test adding multiple tools to the registry."""
        registry = ToolRegistry()
        
        class Args1(BaseModel):
            x: int
        
        class Args2(BaseModel):
            y: str
        
        @registry.tool("tool1", "Tool 1", Args1)
        async def tool1(x: int) -> str:
            return str(x)
        
        @registry.tool("tool2", "Tool 2", Args2)
        async def tool2(y: str) -> str:
            return y.upper()
        
        tools = registry.build()
        
        assert len(tools) == 2
        assert "tool1" in tools
        assert "tool2" in tools
    
    def test_registry_add_method(self):
        """Test add() method for pre-constructed tools."""
        registry = ToolRegistry()
        
        class SimpleArgs(BaseModel):
            x: int
        
        tool = Tool(
            name="manual_tool",
            description="Manually added",
            args_model=SimpleArgs,
            func=lambda x: str(x)
        )
        
        registry.add(tool)
        
        tools = registry.build()
        
        assert "manual_tool" in tools
        assert tools["manual_tool"].description == "Manually added"
    
    def test_registry_get_tool(self):
        """Test get() method."""
        registry = ToolRegistry()
        
        class SimpleArgs(BaseModel):
            x: int
        
        @registry.tool("gettable", "Gettable", SimpleArgs)
        async def gettable(x: int) -> str:
            return str(x)
        
        tool = registry.get("gettable")
        
        assert tool is not None
        assert tool.name == "gettable"
    
    def test_registry_get_nonexistent(self):
        """Test get() with nonexistent tool."""
        registry = ToolRegistry()
        
        tool = registry.get("nonexistent")
        
        assert tool is None
    
    def test_registry_build_returns_copy(self):
        """Test that build() returns a copy."""
        registry = ToolRegistry()
        
        class SimpleArgs(BaseModel):
            x: int
        
        @registry.tool("tool1", "Tool 1", SimpleArgs)
        async def tool1(x: int) -> str:
            return str(x)
        
        tools1 = registry.build()
        tools2 = registry.build()
        
        assert tools1 is not tools2
        assert tools1 == tools2


# =============================================================================
# Test State Isolation
# =============================================================================

class TestStateIsolation:
    """Tests for state isolation across concurrent invocations."""
    
    @pytest.mark.asyncio
    async def test_concurrent_runs_dont_share_state(self, mock_runner_config):
        """Test that concurrent run_stream calls don't share state."""
        call_count = 0
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
            )
            
            delta = DeltaMessage(content=f"Response {call_count}")
            choice = CompletionResponseStreamChoice(
                index=0,
                delta=delta,
                finish_reason="stop"
            )
            chunk = CompletionChunk(
                id=f"cmpl_{call_count}",
                model="mistral-medium-3-5",
                choices=[choice],
                object="chat.completion.chunk"
            )
            event = CompletionEvent(data=chunk)
            yield event
        
        # Make stream_async return a new generator each time it's called
        mock_runner_config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        # Run two concurrent invocations
        results = await asyncio.gather(
            run(mock_runner_config, "Message 1"),
            run(mock_runner_config, "Message 2"),
        )
        
        # Each should have gotten a unique response
        assert results[0] == "Response 1"
        assert results[1] == "Response 2"
        # Should have made 2 separate calls
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_messages_local_to_invocation(self, mock_runner_config):
        """Test that messages list is local to each invocation."""
        messages_seen = []
        
        async def mock_stream():
            # Capture the messages passed to stream_async
            nonlocal messages_seen
            
            event = MagicMock()
            event.data = MagicMock()
            event.data.choices = [MagicMock()]
            event.data.choices[0].finish_reason = "stop"
            event.data.choices[0].delta = MagicMock()
            event.data.choices[0].delta.content = "OK"
            event.data.choices[0].delta.tool_calls = None
            yield event
        
        original_stream_async = mock_runner_config.client.chat.stream_async
        
        async def capturing_stream_async(*args, **kwargs):
            messages_seen.append(kwargs.get("messages", []))
            return mock_stream()
        
        mock_runner_config.client.chat.stream_async = capturing_stream_async
        
        # Run two invocations with different messages
        await run(mock_runner_config, "First message")
        await run(mock_runner_config, "Second message")
        
        # Each should have had its own system message + user message
        assert len(messages_seen) == 2
        assert messages_seen[0][1].content == "First message"
        assert messages_seen[1][1].content == "Second message"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the complete tool runner flow."""
    
    @pytest.mark.asyncio
    async def test_complete_tool_loop_flow(self, mock_runner_config):
        """Test a complete flow: user message -> tool call -> tool result -> final answer."""
        call_count = 0
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            if call_count == 1:
                # First call: model decides to use a tool (no visible text - realistic)
                tool_call = ToolCall(
                    index=0,
                    id="call_1",
                    function=FunctionCall(name="simple_tool", arguments='{"name": "test", "value": 42}'),
                    type="function"
                )
                delta = DeltaMessage(content=None, tool_calls=[tool_call])
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="tool_calls"
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            else:
                # Second call: model gives final answer
                delta = DeltaMessage(content="The answer is 84")
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="stop"
                )
                chunk = CompletionChunk(
                    id="cmpl_2",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
        
        # Make stream_async return a new generator each time it's called
        mock_runner_config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        result = await run(mock_runner_config, "What is the answer?")
        
        # Should have made 2 API calls
        assert call_count == 2
        # Should return the final answer
        assert result == "The answer is 84"
    
    @pytest.mark.asyncio
    async def test_error_recovery_flow(self, mock_runner_config):
        """Test that errors in tool execution are recovered gracefully."""
        call_count = 0
        
        async def make_stream():
            """Factory function to create a new stream each time."""
            nonlocal call_count
            call_count += 1
            
            from mistralai.client.models import (
                CompletionEvent,
                CompletionChunk,
                CompletionResponseStreamChoice,
                DeltaMessage,
                ToolCall,
                FunctionCall,
            )
            
            if call_count == 1:
                # Model tries to use a tool that will fail (no visible text - realistic)
                tool_call = ToolCall(
                    index=0,
                    id="call_1",
                    function=FunctionCall(name="simple_tool", arguments='{"name": "invalid"}'),  # Will fail validation
                    type="function"
                )
                delta = DeltaMessage(content=None, tool_calls=[tool_call])
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="tool_calls"
                )
                chunk = CompletionChunk(
                    id="cmpl_1",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
            else:
                # Model recovers and gives answer directly
                delta = DeltaMessage(content="I'll answer directly instead")
                choice = CompletionResponseStreamChoice(
                    index=0,
                    delta=delta,
                    finish_reason="stop"
                )
                chunk = CompletionChunk(
                    id="cmpl_2",
                    model="mistral-medium-3-5",
                    choices=[choice],
                    object="chat.completion.chunk"
                )
                event = CompletionEvent(data=chunk)
                yield event
        
        # Make stream_async return a new generator each time it's called
        mock_runner_config.client.chat.stream_async.side_effect = lambda *args, **kwargs: make_stream()
        
        result = await run(mock_runner_config, "Test")
        
        # Should have made 2 calls (tool attempt + recovery)
        assert call_count == 2
        # Should return the recovery answer
        assert result == "I'll answer directly instead"
