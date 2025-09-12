import asyncio
import traceback
from typing import Optional
from datetime import datetime
from pydantic import EmailStr
from src.services.gel_client import get_gel_client, get_gel_transaction
from src.models.user import UserCreate, UserResponse, UserUpdate
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class UserService:
    def __init__(self):
        pass  # Gel client is managed globally

    async def create_user(self, user_data: UserCreate) -> UserResponse:
        """
        Create a new user in Gel

        Args:
            user_data: UserCreate model with user data

        Returns:
            UserResponse model with created user data

        Raises:
            ValueError: If user with email already exists
        """
        logger.debug(f"Creating user with email: {user_data.email}")
        logger.debug(f"User data: {user_data.dict()}")

        try:
            client = await get_gel_client()
            logger.debug("Got Gel client")
            
            # First check if user already exists
            check_query = """
                select User
                filter .email = <str>$email
                limit 1
            """

            logger.debug("Checking if user already exists")
            existing_user = await client.query_single(check_query, email=user_data.email)
            if existing_user:
                logger.warning(f"User with email {user_data.email} already exists")
                raise ValueError(f"User with email {user_data.email} already exists")

            # Create the user - Note: identity should be set when integrating with Gel Auth
            current_time = datetime.utcnow().isoformat()
            insert_query = """
                insert User {
                    first_name := <str>$first_name,
                    last_name := <str>$last_name,
                    email := <str>$email,
                    phone := <str>$phone,
                    country := <str>$country,
                    created_at := <datetime>$created_at,
                    updated_at := <datetime>$updated_at
                }
            """

            logger.debug("Executing insert query")
            try:
                await client.execute(insert_query,
                            first_name=user_data.first_name,
                            last_name=user_data.last_name,
                            email=user_data.email,
                            phone=str(user_data.phone),
                            country=user_data.country,
                            created_at=current_time,
                            updated_at=current_time)
            except Exception as query_error:
                logger.error(f"Error executing insert query: {str(query_error)}")
                logger.error(f"Error type: {type(query_error)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                raise

            logger.debug("User created successfully")
            # Return the created user
            return await self.get_user_by_email(user_data.email)
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise

    async def get_user_by_email(self, email: EmailStr) -> Optional[UserResponse]:
        """
        Get a user by email from Gel

        Args:
            email: User's email address

        Returns:
            UserResponse model if found, None otherwise
        """
        logger.debug(f"Getting user by email: {email}")
        try:
            client = await get_gel_client()
            query = """
                select User {
                    first_name,
                    last_name,
                    email,
                    phone,
                    country,
                    created_at,
                    updated_at
                }
                filter .email = <str>$email
                limit 1
            """

            logger.debug("Executing query to get user by email")
            user = await client.query_single(query, email=email)
            if user:
                logger.debug(f"User found: {user}")
                return UserResponse(
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                    phone=user.phone,
                    country=user.country,
                    stytch_user_id="",  # Temporary placeholder - will integrate with auth later
                    created_at=user.created_at,
                    updated_at=user.updated_at
                )
            logger.debug("No user found with that email")
            return None
        except Exception as e:
            logger.error(f"Error getting user by email: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise

    async def update_user(self, email: EmailStr, update_data: UserUpdate) -> Optional[UserResponse]:
        """
        Update a user in Gel

        Args:
            email: User's email address
            update_data: UserUpdate model with fields to update

        Returns:
            Updated UserResponse model if successful, None otherwise
        """
        logger.debug(f"Updating user with email: {email}")
        logger.debug(f"Update data: {update_data.dict()}")

        try:
            client = await get_gel_client()
            # Build update query dynamically
            update_parts = []
            params = {"email": email}

            if update_data.first_name:
                update_parts.append("first_name := <str>$first_name")
                params["first_name"] = update_data.first_name

            if update_data.last_name:
                update_parts.append("last_name := <str>$last_name")
                params["last_name"] = update_data.last_name

            if update_data.phone:
                update_parts.append("phone := <str>$phone")
                params["phone"] = str(update_data.phone)

            if update_data.country:
                update_parts.append("country := <str>$country")
                params["country"] = update_data.country

            # Note: stytch_user_id not in current schema - will add auth integration later

            # Always update the updated_at timestamp
            updated_at = datetime.utcnow().isoformat()
            update_parts.append("updated_at := <datetime>$updated_at")
            params["updated_at"] = updated_at

            if update_parts:
                update_query = f"""
                    update User
                    filter .email = <str>$email
                    set {', '.join(update_parts)}
                """

                logger.debug(f"Executing update query: {update_query}")
                try:
                    await client.execute(update_query, **params)
                    logger.debug("Update query executed successfully")
                except Exception as query_error:
                    logger.error(f"Error executing update query: {str(query_error)}")
                    logger.error(f"Error type: {type(query_error)}")
                    logger.error(f"Stack trace: {traceback.format_exc()}")
                    raise

            # Return updated user
            return await self.get_user_by_email(email)
        except Exception as e:
            logger.error(f"Error updating user: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise
        return None

    async def delete_user(self, email: EmailStr) -> bool:
        """
        Delete a user from Gel

        Args:
            email: User's email address

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Deleting user with email: {email}")
        try:
            client = await get_gel_client()
            query = """
                delete User
                filter .email = <str>$email
            """

            logger.debug("Executing delete query")
            try:
                result = await client.execute(query, email=email)
                logger.debug("Delete query executed successfully")
                return True
            except Exception as query_error:
                logger.error(f"Error executing delete query: {str(query_error)}")
                logger.error(f"Error type: {type(query_error)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                raise
        except Exception as e:
            logger.error(f"Error deleting user: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise
