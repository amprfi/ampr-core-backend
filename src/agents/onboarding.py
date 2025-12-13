from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from convex import ConvexClient
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class OnboardingContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    telegram_id: Optional[str] = None

agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=OnboardingContext,
    output_type=List[str]
)

@agent.tool
async def get_user_info(ctx: RunContext[OnboardingContext]) -> dict:
    """
    Get the current user's information from the database to see what's already filled in.
    Returns user fields like first_name, last_name, email, phone, telegram_id.
    """
    logger.info(f"Tool called: get_user_info for user_id={ctx.deps.user_id}")
    try:
        user = ctx.deps.convex_client.query("users:getUser", {"id": ctx.deps.user_id})
        if not user:
            raise ValueError(f"User {ctx.deps.user_id} not found")
        
        logger.info(f"Tool result: get_user_info returned user data")
        return {
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "telegram_id": user.get("telegram_id")
        }
    except Exception as e:
        error_msg = f"Error retrieving user info: {str(e)}"
        logger.error(f"Tool error: get_user_info - {error_msg}")
        return {"error": error_msg}

@agent.tool
async def update_user_info(
    ctx: RunContext[OnboardingContext],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    telegram_id: Optional[str] = None
) -> str:
    """
    Update the user's information in the database.
    Only provide the fields you want to update.
    Returns success message or error.
    """
    logger.info(f"Tool called: update_user_info for user_id={ctx.deps.user_id}")
    try:
        update_data = {}
        if first_name is not None:
            update_data["first_name"] = first_name
        if last_name is not None:
            update_data["last_name"] = last_name
        if email is not None:
            update_data["email"] = email
        if phone is not None:
            update_data["phone"] = phone
        if telegram_id is not None:
            update_data["telegram_id"] = telegram_id
        
        if not update_data:
            return "No fields to update"
        
        ctx.deps.convex_client.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            **update_data
        })
        
        logger.info(f"Tool result: update_user_info updated fields: {list(update_data.keys())}")
        return f"Successfully updated: {', '.join(update_data.keys())}"
    except Exception as e:
        error_msg = f"Error updating user info: {str(e)}"
        logger.error(f"Tool error: update_user_info - {error_msg}")
        return error_msg

@agent.tool
async def complete_onboarding(ctx: RunContext[OnboardingContext]) -> str:
    """
    Mark the user's onboarding as complete.
    Call this when the user has provided their name OR declined to provide additional info.
    """
    logger.info(f"Tool called: complete_onboarding for user_id={ctx.deps.user_id}")
    try:
        ctx.deps.convex_client.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            "onboarding_complete": True
        })
        logger.info(f"Tool result: Onboarding marked complete for user {ctx.deps.user_id}")
        return "Onboarding marked as complete"
    except Exception as e:
        error_msg = f"Error completing onboarding: {str(e)}"
        logger.error(f"Tool error: complete_onboarding - {error_msg}")
        return error_msg

ONBOARDING_PROMPT = """
You are the Ampersand onboarding assistant. Your job is to help new users complete their profile.

CRITICAL LIMITATIONS:
- You can ONLY use the tools provided (get_user_info, update_user_info, complete_onboarding)
- You CANNOT fetch, look up, or retrieve any external information
- You CANNOT detect or infer the user's location, country, or any other info not explicitly provided
- You must ASK the user for any information you need - never pretend to fetch it

YOUR TASKS:
1. Check what information we already have using get_user_info
2. Ask for missing information in a conversational, friendly way
3. Collect information sequentially (one thing at a time)
4. Update the user record as you collect information using update_user_info
5. Mark onboarding complete using complete_onboarding when appropriate

COLLECTION ORDER:
1. If both first_name AND last_name are missing, ask for full name first
2. Then ask for any missing contact channels (phone, email, telegram) - mention these are optional but helpful

WHEN TO MARK ONBOARDING COMPLETE:
- ONLY after the user has provided their first_name and last_name, you have successfully called update_user_info, and if the user declines to provide more information
- Never proceed to mark onboarding as complete unless you have asked the user to add any missing information
- Call complete_onboarding tool and send as your final messages ["Thanks! I've updated your profile.", "You can always come back to update or add information to your account.", "Now, how can I help you?"]

IMPORTANT: Always call complete_onboarding before returning your final messages!

TONE:
- Be warm and welcoming
- Keep it conversational and brief
- Don't ask for information we already have
- Never mention to the user the fact that the channel they are currently using is connected/linked/stored
- Use plain text only (no markdown formatting)
- Don't overwhelm the user - ask one question at a time

RESPONSE STRUCTURING AND FORMAT:
- Review the conversation history to avoid repeating information you have previously mentioned, like which accounts are connected for the user
- Return your response as a list of messages
- You can break up longer responses, over 25 words, into multiple messages for a more natural conversation flow
- Example: ["Here's what I found.", "Bitcoin is currently trading at $50,000."]
- Each string in the list will be sent as a separate message to the user

"""

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[OnboardingContext]) -> str:
    return ONBOARDING_PROMPT

def get_onboarding_agent():
    return agent
