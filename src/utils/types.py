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
    def from_gel_result(cls, result: dict):
        return cls(
            role=result.llm_role,
            channel=result.channel,
            content=result.body,
            tool_name=result.tool_name,
            tool_args=result.tool_args,
            created_at=result.created_at,
            is_archived=result.is_archived,
        )

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

        if hasattr(message, "content"):
            if isinstance(message.content, str):
                content = message.content
            elif isinstance(message.content, (SystemPromptPart, UserPromptPart, TextPart, RetryPromptPart)):
                content = message.content.content
            elif isinstance(message.content, ToolCallPart):
                tool_name = message.content.tool_name
                tool_args = message.content.args
            elif isinstance(message.content, ToolReturnPart):
                content = str(message.content.content)
                tool_name = message.content.tool_name

        return cls(
            role=role,
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )

    def to_gel_dict(self):
        return {
            "llm_role": self.role,
            "body": self.content,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "created_at": self.created_at,
            "is_archived": self.is_archived,
            "channel": self.channel,
        }

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
                return ModelResponse(
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

    @classmethod
    def from_gel_result(cls, result: dict):
        messages = []
        
        # Convert archive messages if they exist
        if hasattr(result, 'archive') and result.archive:
            for msg in result.archive:
                messages.append(CommonMessage.from_gel_result(msg))
                
        # Convert history messages if they exist  
        if hasattr(result, 'history') and result.history:
            for msg in result.history:
                messages.append(CommonMessage.from_gel_result(msg))
        
        return cls(
            id=result.id,
            messages=messages
        )