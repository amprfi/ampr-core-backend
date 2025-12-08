from pydantic import BaseModel, Field
import uuid
import datetime
from pydantic_ai.messages import ModelMessage
from pydantic_ai.messages import (
    SystemPromptPart,
    UserPromptPart,
    TextPart,
    ToolReturnPart,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.messages import ModelRequest, ModelResponse

class CommonMessage(BaseModel):
    role: str
    channel: str | None = None
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    created_at: datetime.datetime | None = None
    is_archived: bool = False

    @classmethod
    def from_pydantic_ai_message_part(cls, message: ModelMessage):
        match getattr(message, "part_kind", "unknown"):
            case "system-prompt":
                role = "system"
            case "user-prompt":
                role = "user"
            case "text":
                role = "assistant"
            case "tool-call":
                role = "assistant"
            case "tool-return":
                role = "tool"
            case "retry-prompt":
                role = "system"
            case _:
                role = "unknown"

        content = None
        tool_name = None
        tool_args = None

        if isinstance(message, (SystemPromptPart, UserPromptPart, TextPart, RetryPromptPart)):
            content = str(message.content) if message.content is not None else None
        elif isinstance(message, ToolCallPart):
            tool_name = message.tool_name
            tool_args = message.args if isinstance(message.args, dict) else None
        elif isinstance(message, ToolReturnPart):
            content = str(message.content)
            tool_name = message.tool_name

        return cls(
            role=role,
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )

    def to_pydantic_ai_message_part(self):
        match self.role:
            case "system":
                return ModelRequest(
                    parts=[SystemPromptPart(content=self.content or "")]
                )
            case "user":
                return ModelRequest(
                    parts=[UserPromptPart(content=self.content or "")]
                )
            case "assistant":
                if self.tool_name and self.tool_args:
                    return ModelResponse(
                        parts=[ToolCallPart(tool_name=self.tool_name, args=self.tool_args)]
                    )
                else:
                    return ModelResponse(
                        parts=[TextPart(content=self.content or "")]
                    )
            case "tool":
                return ModelRequest(
                    parts=[ToolReturnPart(tool_name=self.tool_name or "", content=self.content or "")]
                )
            case _:
                # Default to text part for unknown roles
                return ModelResponse(
                    parts=[TextPart(content=self.content or "")]
                )

class CommonChat(BaseModel):
    id: uuid.UUID
    messages: list[CommonMessage] = Field(default_factory=list)