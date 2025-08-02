import asyncio
import re
from typing import Optional
from datetime import datetime
from pydantic import EmailStr
from src.services.typedb_client import typedb_client
from typedb.driver import TransactionType
from src.models.user import UserCreate, UserResponse, UserUpdate

def escape_typedb_string(value: str) -> str:
    """Escape special characters for TypeDB string literals"""
    # Escape backslashes and double quotes
    return value.replace('\\', '\\\\').replace('"', '\\"')

class UserService:
    def __init__(self):
        self.typedb = typedb_client

    async def create_user(self, user_data: UserCreate) -> UserResponse:
        """
        Create a new user in TypeDB

        Args:
            user_data: UserCreate model with user data

        Returns:
            UserResponse model with created user data

        Raises:
            ValueError: If user with email already exists
        """
        def _create_user_sync():
            with self.typedb.transaction() as transaction:
                # First check if user already exists
                safe_email = escape_typedb_string(user_data.email)
                check_query = f'''
                match
                $user isa user, has email "{safe_email}";
                '''

                try:
                    # Check for existing user
                    result = transaction.query(check_query).resolve()
                    if list(result):
                        raise ValueError(f"User with email {user_data.email} already exists")

                    # Build the insert query with proper escaping
                    current_time = datetime.utcnow().isoformat()
                    query = f'''
                    insert
                    $user isa user,
                        has first-name "{escape_typedb_string(user_data.first_name)}",
                        has last-name "{escape_typedb_string(user_data.last_name)}",
                        has email "{safe_email}",
                        has phone "{escape_typedb_string(str(user_data.phone))}",
                        has country "{escape_typedb_string(user_data.country)}",
                        has stytch-user-id "{escape_typedb_string(user_data.stytch_user_id)}",
                        has created-at {current_time},
                        has updated-at {current_time};
                    '''

                    # Execute the query using TypeDB 3.x API
                    print(f"Creating user with query: {query}")
                    transaction.query(query).resolve()

                    # Prepare response
                    response = UserResponse(
                        first_name=user_data.first_name,
                        last_name=user_data.last_name,
                        email=user_data.email,
                        phone=user_data.phone,
                        country=user_data.country,
                        stytch_user_id=user_data.stytch_user_id,
                        created_at=datetime.fromisoformat(current_time),
                        updated_at=datetime.fromisoformat(current_time)
                    )
                    print(f"Created user: {response}")
                    return response

                except ValueError:
                    # Re-raise duplicate user error
                    raise
                except Exception as e:
                    print(f"Error creating user: {e}")
                    raise RuntimeError(f"Failed to create user: {e}")

        # Run the synchronous operation in a thread pool
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _create_user_sync)
        except ValueError as e:
            # Re-raise duplicate user error
            raise
        except Exception as e:
            print(f"Error in create_user: {e}")
            raise

    async def get_user_by_email(self, email: EmailStr) -> Optional[UserResponse]:
        """
        Get a user by email from TypeDB

        Args:
            email: User's email address

        Returns:
            UserResponse model if found, None otherwise
        """
        def _get_user_sync():
            with self.typedb.transaction(TransactionType.READ) as transaction:
                safe_email = escape_typedb_string(email)
                query = f'''
                match
                $user isa user, has email "{safe_email}";
                $user has first-name $first_name;
                $user has last-name $last_name;
                $user has email $email_val;
                $user has phone $phone;
                $user has country $country;
                $user has stytch-user-id $stytch_user_id;
                $user has created-at $created_at;
                $user has updated-at $updated_at;
                '''

                try:
                    print(f"Querying user with email: {email}")
                    result = transaction.query(query).resolve()
                    answers = list(result)

                    if answers:
                        # Extract data from the first answer
                        answer = answers[0]
                        first_name = answer.get("first_name").as_attribute().get_value()
                        last_name = answer.get("last_name").as_attribute().get_value()
                        email_val = answer.get("email_val").as_attribute().get_value()
                        phone = answer.get("phone").as_attribute().get_value()
                        country = answer.get("country").as_attribute().get_value()
                        stytch_user_id = answer.get("stytch_user_id").as_attribute().get_value()
                        created_at = datetime.fromisoformat(answer.get("created_at").as_attribute().get_value())
                        updated_at = datetime.fromisoformat(answer.get("updated_at").as_attribute().get_value())

                        return UserResponse(
                            first_name=first_name,
                            last_name=last_name,
                            email=email_val,
                            phone=phone,
                            country=country,
                            stytch_user_id=stytch_user_id,
                            created_at=created_at,
                            updated_at=updated_at
                        )
                    return None
                except Exception as e:
                    print(f"Error getting user: {e}")
                    return None

        # Run the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_user_sync)

    async def update_user(self, email: EmailStr, update_data: UserUpdate) -> Optional[UserResponse]:
        """
        Update a user in TypeDB

        Args:
            email: User's email address
            update_data: UserUpdate model with fields to update

        Returns:
            Updated UserResponse model if successful, None otherwise
        """
        def _update_user_sync():
            with self.typedb.transaction() as transaction:
                safe_email = escape_typedb_string(email)
                # Build the match query with parameter
                match_query = f'match $user isa user, has email "{safe_email}";'

                # Build the delete and insert parts dynamically
                delete_parts = []
                insert_parts = []

                # Collect update parameters
                if update_data.first_name:
                    safe_value = escape_typedb_string(update_data.first_name)
                    delete_parts.append('$user has first-name $old_first_name;')
                    insert_parts.append(f'$user has first-name "{safe_value}";')

                if update_data.last_name:
                    safe_value = escape_typedb_string(update_data.last_name)
                    delete_parts.append('$user has last-name $old_last_name;')
                    insert_parts.append(f'$user has last-name "{safe_value}";')

                if update_data.phone:
                    safe_value = escape_typedb_string(str(update_data.phone))
                    delete_parts.append('$user has phone $old_phone;')
                    insert_parts.append(f'$user has phone "{safe_value}";')

                if update_data.country:
                    safe_value = escape_typedb_string(update_data.country)
                    delete_parts.append('$user has country $old_country;')
                    insert_parts.append(f'$user has country "{safe_value}";')

                # Always update the updated-at timestamp
                updated_at = datetime.utcnow().isoformat()
                delete_parts.append('$user has updated-at $old_updated_at;')
                insert_parts.append(f'$user has updated-at {updated_at};')

                if delete_parts and insert_parts:
                    query = match_query + '\ndelete\n' + '\n'.join(delete_parts) + '\ninsert\n' + '\n'.join(insert_parts)

                    try:
                        print(f"Updating user with query: {query}")
                        result = transaction.query(query).resolve()
                        print(f"User update result: {result}")

                        # Return updated user - get fresh data from database
                        return self.get_user_by_email(email)
                    except Exception as e:
                        print(f"Error updating user: {e}")
                        return None
                return None

        # Run the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _update_user_sync)

    async def delete_user(self, email: EmailStr) -> bool:
        """
        Delete a user from TypeDB

        Args:
            email: User's email address

        Returns:
            True if successful, False otherwise
        """
        def _delete_user_sync():
            with self.typedb.transaction() as transaction:
                safe_email = escape_typedb_string(email)
                query = f'''
                match
                $user isa user, has email "{safe_email}";
                delete
                $user isa user;
                '''

                try:
                    print(f"Deleting user with email: {email}")
                    result = transaction.query(query).resolve()
                    print(f"User deletion result: {result}")
                    return True
                except Exception as e:
                    print(f"Error deleting user: {e}")
                    return False

        # Run the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _delete_user_sync)
