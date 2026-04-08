from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
import logging
from typing import Optional

from convex import ConvexClient

from ..base import BaseModule

logger = logging.getLogger(__name__)


class LensContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    lens_id: str
    lens_name: str
    publisher: Optional[str] = None
    system_prompt: str


agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=LensContext,
)


@agent.tool
async def search_content(
    ctx: RunContext[LensContext],
    query: str,
) -> str:
    """
    Search the author's indexed content for passages relevant to a query.

    Args:
        query: A focused search query describing what you're looking for
            in the author's writings.

    Returns:
        Relevant content passages with source document titles.
    """
    logger.info(f"Tool called: search_content for lens={ctx.deps.lens_name}, query='{query}'")

    try:
        result = ctx.deps.convex_client.action("lenses:searchByText", {
            "lensId": ctx.deps.lens_id,
            "query": query,
            "limit": 10,
        })

        chunks = result.get("chunks", [])
        top_documents = result.get("topDocuments", [])

        if not chunks:
            return "No relevant content found for this query."

        # Format chunks with document attribution
        lines = []
        for chunk in chunks[:5]:
            title = chunk.get("documentTitle", "Unknown")
            content = chunk.get("content", "")
            score = chunk.get("score", 0)
            lines.append(f"[{title}] (relevance: {score:.3f})\n{content}")

        # Append full document context for the top-scoring documents
        if top_documents:
            lines.append("\n--- Full Document Context ---")
            for doc in top_documents:
                title = doc.get("title", "Unknown")
                summary = doc.get("summary", "")
                lines.append(f"\n**{title}**\nSummary: {summary}")

        result_text = "\n\n".join(lines)
        logger.info(f"Tool result: search_content returned {len(chunks)} chunks, {len(top_documents)} top docs")
        return result_text

    except Exception as e:
        error_msg = f"Failed to search content: {str(e)}"
        logger.error(f"Tool error: search_content - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = (Path(__file__).parent / "prompt.md").read_text()


@agent.system_prompt
def get_system_prompt(ctx: RunContext[LensContext]) -> str:
    publisher_line = (
        f"You are representing the publisher **{ctx.deps.publisher}** "
        if ctx.deps.publisher
        else "You are representing "
    )
    return (
        f"{publisher_line}through the lens called **{ctx.deps.lens_name}**.\n\n"
        f"Author's guidance:\n{ctx.deps.system_prompt}\n\n"
        + PROMPT_TEMPLATE
    )


class LensModule(BaseModule):
    """
    Lens module for RAG-powered author agent interactions.
    Searches an author's indexed content and responds from their perspective.
    """

    def __init__(self, convex_client: Optional[ConvexClient] = None):
        super().__init__(name="lens", trigger="&lens")
        self._convex_client_instance = convex_client

    def _get_convex_client(self) -> ConvexClient:
        if self._convex_client_instance:
            return self._convex_client_instance
        if self._convex_client:
            return self._convex_client
        from ...clients.convex_client import get_client
        return get_client()

    async def invoke(self, message: str, date_context: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """
        Process a user message by resolving the lens name from the message,
        loading the lens metadata, and running the agent.

        The message is expected to contain "&lens:<name>" to identify which lens to use.

        Args:
            user_id: Optional core Convex user_id (unused by this module but
                required for interface consistency).
        """
        try:
            logger.info(f"Lens module invoked with message: {message}")

            client = self._get_convex_client()

            # Extract lens name from the trigger pattern "&lens:<name>"
            lens_name = self._extract_lens_name(message)
            if not lens_name:
                return "Please specify a lens using the format: &lens:author_name"

            # Load the lens metadata from Convex
            lens = client.query("lenses:getLensByName", {"name": lens_name})
            if not lens:
                return f"Lens '{lens_name}' not found."

            agent_input = message
            if date_context:
                agent_input = f"{message}\n\n{date_context}"

            context = LensContext(
                convex_client=client,
                lens_id=lens["_id"],
                lens_name=lens["name"],
                publisher=lens.get("publisher"),
                system_prompt=lens["systemPrompt"],
            )

            result = await agent.run(agent_input, deps=context)

            response = result.output
            logger.info(f"Lens response: {response}")

            return response

        except Exception as e:
            error_msg = f"Lens module error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    @staticmethod
    def _extract_lens_name(message: str) -> Optional[str]:
        """Extract lens name from '&lens:name' pattern in the message."""
        import re
        match = re.search(r"&lens:(\S+)", message)
        return match.group(1) if match else None


def get_lens_module(convex_client: Optional[ConvexClient] = None) -> LensModule:
    """Factory function to create a Lens module instance."""
    return LensModule(convex_client=convex_client)
