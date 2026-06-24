"""
Streaming response handler for AI SDK UI-compatible token-level chat streaming.

This module provides the streaming implementation for the `/api/chat/stream` endpoint
(AMPRFI-114). It emits the Vercel AI SDK UI Message Stream data protocol with:
- Standard parts: start, text-start, text-delta, text-end, finish
- Custom data-* parts for Ampersand-specific metadata (module lifecycle, status, attribution)

The streaming flow:
1. Runs preprocessing (stores user message, detects modules, infers context)
2. For each module/response, creates a tagged async iterator wrapping amprChat.stream()
3. Merges iterators to interleave faster modules before slower ones finish
4. Converts text deltas to SSE-formatted AI SDK UI stream parts
5. Emits custom data-* parts for module attribution, status, and lifecycle
6. Accumulates final text per response/module during streaming
7. After aggregate turn completes successfully, persists all assistant messages
8. If turn fails, does NOT persist partial assistant output

Key design decisions:
- Uses FastAPI StreamingResponse with custom async generator (no external deps)
- State is isolated per synthesis stream (no shared mutable state)
- Thinking chunks are NEVER yielded to the client (consumed internally)
- Multi-module streams run concurrently via asyncio.gather on tagged iterators
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

from .context import ResponseContext
from .context_builder import build_context_string
from .synthesis_context import build_module_synthesis_context
from .preprocessing import run_preprocessing
from .postprocessing import schedule_memory_management, schedule_profile_watcher
from src.agents.amprChat import get_amprChat_agent, TalkerContext
from src.modules.registry import get_module_registry

logger = logging.getLogger(__name__)


# ============================================================================
# ID Generation Helpers
# ============================================================================

def _generate_message_id(user_id: str) -> str:
    """Generate a deterministic message ID for the AI SDK UI protocol."""
    # Use a hash based on user_id and current timestamp for uniqueness
    timestamp = str(time.time_ns())
    unique_str = f"{user_id}_{timestamp}"
    hash_obj = hashlib.sha256(unique_str.encode())
    hex_digest = hash_obj.hexdigest()[:16]  # Use first 16 chars for brevity
    return f"msg_{hex_digest}"


def _generate_text_block_id(base: str) -> str:
    """Generate a deterministic text block ID for the AI SDK UI protocol."""
    # Use a hash based on the base (module name or 'general') and timestamp
    timestamp = str(time.time_ns())
    unique_str = f"{base}_{timestamp}"
    hash_obj = hashlib.sha256(unique_str.encode())
    hex_digest = hash_obj.hexdigest()[:16]
    return f"text_{hex_digest}"


# ============================================================================
# AI SDK UI Message Stream Protocol Types
# ============================================================================

class StreamPartType(Enum):
    """Standard AI SDK UI Message Stream part types."""
    START = "start"
    TEXT_START = "text-start"
    TEXT_DELTA = "text-delta"
    TEXT_END = "text-end"
    FINISH = "finish"


# Custom Ampersand data part types (prefixed with "data-")
class CustomPartType(Enum):
    """Custom Ampersand-specific stream part types."""
    MODULE_START = "data-module-start"
    MODULE_TEXT = "data-module-text"
    MODULE_END = "data-module-end"
    MODULE_ERROR = "data-module-error"
    MODULE_METADATA = "data-module-metadata"
    STATUS = "data-status"
    TURN_METADATA = "data-turn-metadata"
    UNRESOLVED_TRIGGERS = "data-unresolved-triggers"
    TURN_COMPLETE = "data-turn-complete"


@dataclass
class StreamPart:
    """Represents a single part in the AI SDK UI Message Stream."""
    part_type: str  # Standard or custom part type
    data: dict[str, Any]  # The data payload for this part
    
    def to_sse(self) -> str:
        """Convert to SSE format: 'data: {json}\n\n'"""
        return f"data: {json.dumps(self.data)}\n\n"



@dataclass
class AggregateStreamState:
    """
    State for the aggregate streaming turn.
    
    Tracks all active module streams and accumulates results for
    persistence after successful completion.
    """
    # Preprocessing results (shared across all modules)
    preprocess_result: Any
    
    # Module stream tracking (no defaults - must be provided)
    modules: list[str]  # List of module names (empty for zero-module)
    
    # Message and text block IDs for AI SDK UI protocol conformance
    message_id: str = ""
    text_block_ids: dict[str, str] = field(default_factory=dict)  # module_name -> text_block_id
    
    # Accumulated interim messages (from preprocessing)
    interim_messages: list[str] = field(default_factory=list)
    
    # Error tracking
    has_errors: bool = False
    error_messages: list[str] = field(default_factory=list)
    
    # Completion tracking
    completed_modules: set[str] = field(default_factory=set)
    failed_modules: set[str] = field(default_factory=set)
    
    # Final accumulated content for persistence (with message IDs tracked after persistence)
    final_messages: list[dict[str, Any]] = field(default_factory=list)
    persisted_message_ids: list[str] = field(default_factory=list)  # Track IDs of persisted messages
    
    def mark_module_complete(self, module_name: Optional[str], content: str) -> None:
        """Mark a module as successfully completed."""
        if module_name:
            self.completed_modules.add(module_name)
        # Add to final messages for persistence
        self.final_messages.append({
            "content": content,
            "specialist_module": module_name
        })
    
    def mark_module_error(self, module_name: Optional[str], error: str) -> None:
        """Mark a module as failed with an error."""
        if module_name:
            self.failed_modules.add(module_name)
        self.has_errors = True
        self.error_messages.append(error)
    
    def is_aggregate_successful(self) -> bool:
        """Check if the aggregate turn was successful (no errors)."""
        return not self.has_errors


# ============================================================================
# Stream Part Generators
# ============================================================================

def _create_start_part(message_id: str) -> StreamPart:
    """Create the aggregate start part with required messageId."""
    return StreamPart(
        part_type=StreamPartType.START.value,
        data={"type": StreamPartType.START.value, "messageId": message_id}
    )


def _create_text_start_part(text_block_id: str) -> StreamPart:
    """Create the text-start part with required id."""
    return StreamPart(
        part_type=StreamPartType.TEXT_START.value,
        data={"type": StreamPartType.TEXT_START.value, "id": text_block_id}
    )


def _create_text_delta_part(delta: str, text_block_id: str) -> StreamPart:
    """Create a text-delta part with the exact standard protocol fields."""
    data = {"type": StreamPartType.TEXT_DELTA.value, "id": text_block_id, "delta": delta}
    return StreamPart(part_type=StreamPartType.TEXT_DELTA.value, data=data)


def _create_text_end_part(text_block_id: str) -> StreamPart:
    """Create the text-end part with required id."""
    return StreamPart(
        part_type=StreamPartType.TEXT_END.value,
        data={"type": StreamPartType.TEXT_END.value, "id": text_block_id}
    )


def _create_finish_part() -> StreamPart:
    """Create the finish part with the exact v6 protocol shape."""
    return StreamPart(
        part_type=StreamPartType.FINISH.value,
        data={"type": StreamPartType.FINISH.value}
    )


def _create_module_start_part(module_name: str, display_name: str) -> StreamPart:
    """Create a custom module-start part with payload wrapped in data field."""
    return StreamPart(
        part_type=CustomPartType.MODULE_START.value,
        data={
            "type": CustomPartType.MODULE_START.value,
            "data": {
                "module": module_name,
                "displayName": display_name
            }
        }
    )


def _create_module_text_part(module_name: str, delta: str, text_block_id: str) -> StreamPart:
    """Create a custom module-attributed text-delta part with payload wrapped in data field."""
    return StreamPart(
        part_type=CustomPartType.MODULE_TEXT.value,
        data={
            "type": CustomPartType.MODULE_TEXT.value,
            "data": {
                "module": module_name,
                "delta": delta,
                "id": text_block_id
            }
        }
    )


def _create_module_end_part(module_name: str, text_block_id: str) -> StreamPart:
    """Create a custom module-end part with payload wrapped in data field."""
    return StreamPart(
        part_type=CustomPartType.MODULE_END.value,
        data={
            "type": CustomPartType.MODULE_END.value,
            "data": {
                "module": module_name,
                "id": text_block_id
            }
        }
    )


def _create_module_error_part(module_name: str, error: str, text_block_id: Optional[str] = None) -> StreamPart:
    """Create a custom module-error part with payload wrapped in data field."""
    error_data = {"module": module_name, "error": error}
    if text_block_id:
        error_data["id"] = text_block_id
    return StreamPart(
        part_type=CustomPartType.MODULE_ERROR.value,
        data={
            "type": CustomPartType.MODULE_ERROR.value,
            "data": error_data
        }
    )


def _create_unresolved_triggers_part(triggers: list[str]) -> StreamPart:
    """Create a custom unresolved triggers notice part with payload wrapped in data field."""
    return StreamPart(
        part_type=CustomPartType.UNRESOLVED_TRIGGERS.value,
        data={
            "type": CustomPartType.UNRESOLVED_TRIGGERS.value,
            "data": {"triggers": triggers}
        }
    )


def _create_status_part(message: str, category: str = "interim") -> StreamPart:
    """Create a transient status data part for non-persisted progress metadata."""
    return StreamPart(
        part_type=CustomPartType.STATUS.value,
        data={
            "type": CustomPartType.STATUS.value,
            "data": {
                "category": category,
                "message": message,
            }
        }
    )


def _create_turn_metadata_part(
    modules: list[str],
    interim_messages: list[str],
    unresolved_triggers: list[str]
) -> StreamPart:
    """Create a custom turn metadata part with payload wrapped in data field."""
    return StreamPart(
        part_type=CustomPartType.TURN_METADATA.value,
        data={
            "type": CustomPartType.TURN_METADATA.value,
            "data": {
                "modules": modules,
                "interimMessageCount": len(interim_messages),
                "unresolvedTriggerCount": len(unresolved_triggers)
            }
        }
    )


def _create_turn_complete_part(message_id: str, message_ids: list[str], has_errors: bool) -> StreamPart:
    """Create a custom turn-complete part with persisted message metadata."""
    return StreamPart(
        part_type=CustomPartType.TURN_COMPLETE.value,
        data={
            "type": CustomPartType.TURN_COMPLETE.value,
            "data": {
                "messageId": message_id,
                "messageIds": message_ids,
                "hasErrors": has_errors
            }
        }
    )


def _create_error_part(error_text: str) -> StreamPart:
    """Create a standard error part for stream-level errors."""
    return StreamPart(
        part_type="error",
        data={"type": "error", "errorText": error_text}
    )


def _create_done_terminator() -> str:
    """Create the [DONE] terminator for the stream."""
    return "data: [DONE]\n\n"


# ============================================================================
# Module Stream Wrapper
# ============================================================================

async def _create_module_stream(
    context: ResponseContext,
    preprocess_result: Any,
    module_name: Optional[str],
    synthesis_context: str,
    module_registry: Any,
    state: AggregateStreamState
) -> AsyncIterator[StreamPart]:
    """
    Create a tagged async iterator that wraps a module's synthesis stream.
    
    This generator:
    1. Emits module-start part
    2. Yields text-delta parts from the amprChat stream
    3. Emits module-end part on successful completion
    4. Emits module-error part on failure
    5. Accumulates content in the aggregate state
    
    Args:
        context: ResponseContext for the request
        preprocess_result: PreprocessingResult with all collected data
        module_name: The module name (None for general chat)
        synthesis_context: The context string for this module's synthesis
        module_registry: ModuleRegistry instance
        state: AggregateStreamState to track progress
        
    Yields:
        StreamPart objects for the AI SDK UI Message Stream
    """
    # Get or generate text block ID for this module/general chat
    if module_name:
        if module_name not in state.text_block_ids:
            state.text_block_ids[module_name] = _generate_text_block_id(module_name)
        text_block_id = state.text_block_ids[module_name]
    else:
        # General chat - use a default key
        if "__general__" not in state.text_block_ids:
            state.text_block_ids["__general__"] = _generate_text_block_id("general")
        text_block_id = state.text_block_ids["__general__"]
    
    # Get user-friendly display name for the module
    if module_name:
        meta = module_registry.metadata.get(module_name, {})
        display_name = meta.get("trigger", f"&{module_name}").lstrip("&")
    else:
        display_name = "general"
    
    # Build TalkerContext for this module
    invoked_modules = [module_name] if module_name else []
    talker_context = TalkerContext(
        convex_client=context.convex_client,
        user_id=context.user_id,
        date_context=preprocess_result.date_context_str,
        invoked_modules=invoked_modules,
        channel=context.channel,
        telegram_id=context.telegram_id,
    )
    
    # Emit module lifecycle parts only for actual specialist modules.
    # Module streams also emit standard text-* parts so default AI SDK UI
    # rendering shows module responses even if custom data-* rendering is absent.
    emitted_text_start = False
    if module_name:
        yield _create_module_start_part(module_name, display_name)
        yield _create_text_start_part(text_block_id)
        emitted_text_start = True
    
    # Accumulate text deltas for this module
    accumulated_content: list[str] = []
    last_error: Optional[Exception] = None
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            agent_start = time.monotonic()
            amprChat_agent = get_amprChat_agent()
            
            async for delta in amprChat_agent.stream(synthesis_context, deps=talker_context):
                # Accumulate content
                accumulated_content.append(delta)
                
                if module_name:
                    # Standard text deltas keep default useChat() rendering working.
                    yield _create_text_delta_part(delta, text_block_id)
                    # Custom data deltas carry Ampersand module attribution.
                    yield _create_module_text_part(module_name, delta, text_block_id)
                else:
                    # For general chat, use standard text-delta
                    yield _create_text_delta_part(delta, text_block_id)
            
            agent_elapsed = round(time.monotonic() - agent_start, 2)
            logger.info(
                f"Streaming synthesis completed for '{module_name or 'general'}' "
                f"in {agent_elapsed}s (attempt {attempt + 1})"
            )
            
            # Module completed successfully
            final_content = "".join(accumulated_content)
            state.mark_module_complete(module_name, final_content)
            
            # Emit module end
            if module_name:
                yield _create_text_end_part(text_block_id)
                yield _create_module_end_part(module_name, text_block_id)
            return
            
        except Exception as e:
            last_error = e
            error_msg = str(e)
            err_str = error_msg.lower()
            is_transient = "503" in err_str or "overloaded" in err_str or "rate" in err_str
            can_retry_without_duplication = not accumulated_content
            
            if is_transient and can_retry_without_duplication and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                logger.warning(
                    f"Transient streaming synthesis error for '{module_name or 'general'}' "
                    f"(attempt {attempt + 1}/{max_retries}), retrying in {wait}s: {error_msg}"
                )
                await asyncio.sleep(wait)
                continue
            
            if is_transient and not can_retry_without_duplication:
                logger.warning(
                    f"Transient streaming synthesis error for '{module_name or 'general'}' occurred "
                    "after visible output was sent; not retrying to avoid duplicate text."
                )
            break
    
    error_msg = str(last_error) if last_error else "Unknown streaming error"
    state.mark_module_error(module_name, error_msg)
    logger.error(f"Module '{module_name or 'general'}' stream failed: {error_msg}", exc_info=last_error)
    
    # Emit error metadata. If a module opened a standard text part, close it
    # before the module-error so the AI SDK UI text lifecycle remains valid.
    if module_name:
        if emitted_text_start:
            yield _create_text_end_part(text_block_id)
        yield _create_module_error_part(module_name, error_msg, text_block_id)
    else:
        yield _create_error_part(error_msg)
    
    # Note: We don't re-raise errors here. Instead, we let the aggregate
    # handler check state.has_errors to determine if persistence should happen.
    # This allows us to continue streaming even if some modules fail.


async def _create_interim_stream(
    interim_messages: list[str]
) -> AsyncIterator[StreamPart]:
    """
    Create a stream for interim messages (non-module, pre-synthesis messages).
    
    These are messages like "Module X is working on this..." or 
    "Module Y could not be found" that were accumulated during preprocessing.
    
    Args:
        interim_messages: List of interim message strings
        
    Yields:
        StreamPart objects for each transient status message
    """
    for msg in interim_messages:
        # Keep ephemeral progress/not-found notices out of the persisted assistant text.
        yield _create_status_part(msg, category="interim")


# ============================================================================
# Stream Merger
# ============================================================================

async def _merge_streams(
    streams: dict[str, AsyncIterator[StreamPart]],
    state: AggregateStreamState
) -> AsyncIterator[StreamPart]:
    """
    Merge multiple async iterators, yielding parts as they arrive.
    
    Uses a SINGLE shared queue that all reader tasks put into.
    Each reader task consumes its stream and puts parts (tagged with source)
    into the shared queue. The merger drains the shared queue and yields parts.
    
    This fixes the concurrency bug where:
    - Per-iteration FIRST_COMPLETED created orphaned tasks
    - Pending tasks were never cancelled
    - Reader tasks could be GC'd (not reference-held)
    
    Args:
        streams: Dictionary mapping module names to their async iterators
        state: AggregateStreamState to track progress
        
    Yields:
        StreamPart objects from all streams, interleaved
    """
    # Create a SINGLE shared queue for all streams
    shared_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    
    # Hold references to all reader tasks to prevent GC
    reader_tasks: list[asyncio.Task] = []
    
    async def _reader(name: str, stream: AsyncIterator[StreamPart]) -> None:
        """Read from a stream and put parts into the shared queue."""
        try:
            async for part in stream:
                # Tag the part with its source stream name for debugging
                # (not strictly needed but helps with tracing)
                await shared_queue.put((name, part))
        except Exception as e:
            # Stream error - mark as failed and log
            error_msg = str(e)
            state.mark_module_error(name, error_msg)
            logger.error(f"Stream reader for '{name}' failed: {error_msg}", exc_info=True)
        finally:
            # Put a sentinel to signal this stream completed
            await shared_queue.put((name, None))
    
    # Start all reader tasks and hold references
    for name, stream in streams.items():
        task = asyncio.create_task(_reader(name, stream))
        reader_tasks.append(task)
    
    # Track which streams have completed
    completed_streams: set[str] = set()
    active_streams: set[str] = set(streams.keys())
    
    # Drain the shared queue until all streams complete
    while len(completed_streams) < len(streams):
        # Get the next item from the shared queue
        source_name, part = await shared_queue.get()
        
        if part is None:
            # Sentinel: stream completed
            completed_streams.add(source_name)
            active_streams.discard(source_name)
        else:
            # Yield the part
            yield part
    
    # All streams have completed
    # Clean up: cancel any remaining reader tasks (should all be done)
    for task in reader_tasks:
        if not task.done():
            task.cancel()
    
    # Wait for all reader tasks to finish cleanup
    if reader_tasks:
        await asyncio.wait(reader_tasks, return_when=asyncio.ALL_COMPLETED)


# ============================================================================
# Main Streaming Generator
# ============================================================================

async def _generate_stream_parts(
    context: ResponseContext
) -> AsyncIterator[StreamPart]:
    """
    Generate the complete AI SDK UI Message Stream for a chat request.
    
    This is the main generator that:
    1. Runs preprocessing
    2. Emits aggregate start
    3. Handles zero/single/multi-module cases
    4. Creates and merges module streams
    5. Emits text deltas and custom parts
    6. Emits aggregate finish
    7. Persists assistant messages after successful completion
    
    Args:
        context: ResponseContext for the request
        
    Yields:
        StreamPart objects in AI SDK UI Message Stream format
    """
    # Step 1: Run preprocessing (stores user message, detects modules, etc.)
    preprocess_result = await run_preprocessing(context)
    
    # Generate message ID for AI SDK UI protocol
    message_id = _generate_message_id(context.user_id)
    
    # Handle bare &help fast path
    if preprocess_result.is_bare_help:
        help_text = preprocess_result.help_text
        
        # Generate text block ID for help response
        help_text_block_id = _generate_text_block_id("help")
        
        # Emit aggregate start with messageId
        yield _create_start_part(message_id)
        
        # Emit text parts for help response with proper IDs
        yield _create_text_start_part(help_text_block_id)
        yield _create_text_delta_part(help_text, help_text_block_id)
        yield _create_text_end_part(help_text_block_id)
        
        # Persist the help response
        result = await context.async_convex_client.mutation("messages:createMessage", {
            "userId": context.user_id,
            "role": "assistant",
            "channel": context.channel,
            "content": help_text
        })
        persisted_msg_id = result.get("_id", "")
        
        # Schedule background tasks
        schedule_memory_management(context)
        
        # Emit finish with exact v6 shape, then persisted metadata in a custom part.
        yield _create_finish_part()
        if persisted_msg_id:
            yield _create_turn_complete_part(
                message_id=message_id,
                message_ids=[persisted_msg_id],
                has_errors=False,
            )
        
        # Emit [DONE] terminator
        yield StreamPart(part_type="done", data={})
        return
    
    # Initialize aggregate state with message_id
    state = AggregateStreamState(
        preprocess_result=preprocess_result,
        modules=preprocess_result.modules or [],
        interim_messages=preprocess_result.interim_messages or [],
        message_id=message_id
    )
    
    # Get module registry
    module_registry = get_module_registry()
    
    # Step 2: Emit aggregate start with messageId
    yield _create_start_part(state.message_id)
    
    # Step 3: Emit turn metadata
    yield _create_turn_metadata_part(
        modules=state.modules,
        interim_messages=state.interim_messages,
        unresolved_triggers=preprocess_result.unresolved_triggers or []
    )
    
    # Step 4: Emit unresolved triggers notice if any
    if preprocess_result.unresolved_triggers:
        yield _create_unresolved_triggers_part(preprocess_result.unresolved_triggers)
    
    # Step 5: Create streams for each module/response
    streams: dict[str, AsyncIterator[StreamPart]] = {}
    
    # Generate transient status events for interim messages (if any)
    if state.interim_messages:
        streams["__interim__"] = _create_interim_stream(state.interim_messages)
    
    # Determine the synthesis approach based on number of modules
    modules = state.modules
    module_responses = preprocess_result.module_responses or {}
    
    if len(modules) > 1:
        # Multi-module case: create a stream for each module
        for module_name in modules:
            module_response = module_responses.get(module_name, "")
            
            # Build cross-module awareness context
            other_modules = [m for m in modules if m != module_name]
            other_module_names = [
                module_registry.metadata.get(m, {}).get("trigger", f"&{m}") 
                for m in other_modules
            ]
            cross_module_context = (
                f"Other responding modules: {', '.join(other_module_names)}" 
                if other_modules else ""
            )
            
            # Build module-specific context for synthesis
            synthesis_context = build_module_synthesis_context(
                preprocess_result, module_registry, module_name, 
                module_response, cross_module_context
            )
            
            # Create the module stream
            streams[module_name] = _create_module_stream(
                context, preprocess_result, module_name, 
                synthesis_context, module_registry, state
            )
    
    elif len(modules) == 1:
        # Single-module case
        module_name = modules[0]
        module_response = module_responses.get(module_name, "")
        
        # Build context for synthesis
        synthesis_context = build_module_synthesis_context(
            preprocess_result, module_registry, module_name,
            module_response, ""
        )
        
        # Create the module stream
        streams[module_name] = _create_module_stream(
            context, preprocess_result, module_name,
            synthesis_context, module_registry, state
        )
    
    else:
        # Zero-module case: general amprChat
        # Build context without module response
        synthesis_context = build_context_string(
            preprocess_result.summaries_str,
            preprocess_result.message_history_str,
            preprocess_result.message_content,
            preprocess_result.date_context_str,
            preprocess_result.currency_context,
            None,  # No module name
            None,  # No module response
            preprocess_result.unresolved_triggers,
            registry=module_registry,
        )
        
        # Create general chat stream (no module attribution)
        streams["__general__"] = _create_module_stream(
            context, preprocess_result, None,  # None for general chat
            synthesis_context, module_registry, state
        )
    
    # Step 6: Emit text-start for the zero-module general response.
    # Store the generated ID before the stream is consumed so text-start,
    # text-delta, and text-end all use the same protocol ID.
    if len(modules) == 0:
        if "__general__" not in state.text_block_ids:
            state.text_block_ids["__general__"] = _generate_text_block_id("general")
        general_text_block_id = state.text_block_ids["__general__"]
        yield _create_text_start_part(general_text_block_id)
    
    # Step 7: Merge and yield from all streams
    # Note: _merge_streams handles errors internally and marks state accordingly
    # We don't wrap in try/except because individual module errors are already
    # caught and emitted as data-module-error parts
    async for part in _merge_streams(streams, state):
        yield part
    
    # Step 8: Emit text-end for zero-module case
    if len(modules) == 0:
        general_text_block_id = state.text_block_ids["__general__"]
        yield _create_text_end_part(general_text_block_id)
    
    # Step 9: Persist assistant messages if aggregate turn was successful
    if state.is_aggregate_successful():
        # Persist each final message with its module attribution
        for msg_data in state.final_messages:
            message_args: dict = {
                "userId": context.user_id,
                "role": "assistant",
                "channel": context.channel,
                "content": msg_data["content"]
            }
            if msg_data.get("specialist_module"):
                message_args["specialist_module"] = msg_data["specialist_module"]
            
            result = await context.async_convex_client.mutation("messages:createMessage", message_args)
            state.persisted_message_ids.append(result.get("_id", ""))
        
        # Schedule background tasks
        schedule_memory_management(context)
        
        # For post-onboarding users, watch for profile-relevant info
        if not preprocess_result.needs_onboarding:
            schedule_profile_watcher(context, context.message_content)
        
        logger.info(f"Persisted {len(state.final_messages)} assistant messages for chat {context.chat_id}")
    else:
        # Aggregate turn failed - do NOT persist partial assistant output
        logger.warning(
            f"Aggregate turn failed with {len(state.error_messages)} errors. "
            f"Not persisting {len(state.final_messages)} partial assistant messages."
        )
    
    # Step 10: Emit finish part (v6 spec requires exactly {"type":"finish"})
    yield _create_finish_part()
    
    # Step 11: Emit turn-complete part with persisted message metadata
    # This carries the message IDs that the frontend needs for its onFinish split
    if state.persisted_message_ids:
        yield _create_turn_complete_part(
            message_id=state.message_id,
            message_ids=state.persisted_message_ids,
            has_errors=state.has_errors
        )
    
    # Step 12: Emit [DONE] terminator
    yield StreamPart(part_type="done", data={})


# ============================================================================
# SSE Formatter
# ============================================================================

async def _format_sse_stream(
    parts: AsyncIterator[StreamPart]
) -> AsyncIterator[str]:
    """
    Format stream parts as SSE (Server-Sent Events).
    
    Each part is converted to: 'data: {json}\n\n'
    The special "done" part is converted to 'data: [DONE]\n\n'
    
    Args:
        parts: Async iterator of StreamPart objects
        
    Yields:
        SSE-formatted strings
    """
    async for part in parts:
        if part.part_type == "done":
            # Emit [DONE] terminator
            yield "data: [DONE]\n\n"
        else:
            yield part.to_sse()


# ============================================================================
# Public API
# ============================================================================

async def generate_streaming_response(
    context: ResponseContext
) -> AsyncIterator[str]:
    """
    Generate a streaming response for the AI SDK UI Message Stream protocol.
    
    This is the main entry point for the `/api/chat/stream` endpoint.
    It returns an async iterator of SSE-formatted strings that conform to
    the AI SDK UI Message Stream data protocol.
    
    The response includes:
    - Required header: x-vercel-ai-ui-message-stream: v1
    - Content-Type: text/event-stream
    - Standard AI SDK UI parts: start, text-start, text-delta, text-end, finish
    - Custom Ampersand parts: data-module-*, data-unresolved-triggers, etc.
    
    Args:
        context: ResponseContext containing all request information
        
    Yields:
        SSE-formatted strings for the AI SDK UI Message Stream
    """
    # Generate the stream parts
    parts = _generate_stream_parts(context)
    
    # Format as SSE
    async for sse_string in _format_sse_stream(parts):
        yield sse_string
