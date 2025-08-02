import asyncio
from typing import Optional
from datetime import datetime
from pydantic import EmailStr
from src.services.typedb_client import typedb_client
from typedb.driver import TransactionType
from src.services.auth_client import stytch_client
from src.models.user import UserCreate, UserResponse, UserUpdate

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
        """
        def _create_user_sync():
            with self.typedb.transaction() as transaction:
                # Build the insert query
                query = '''
                insert
                $user isa user,
                    has first-name "''' + user_data.first_name + '''",
                    has last-name "''' + user_data.last_name + '''",
                    has email "''' + user_data.email + '''",
                    has phone "''' + str(user_data.phone) + '''",
                    has country "''' + user_data.country + '''",
                    has stytch-user-id "''' + user_data.stytch_user_id + '''",
                    has created-at ''' + datetime.utcnow().isoformat() + ''',
                    has updated-at ''' + datetime.utcnow().isoformat() + ''';
                '''

                # Execute the query using TypeDB 3.x API
                print(f"Creating user with query: {query}")
                result = transaction.query(query).resolve()
                print(f"User creation result: {result}")

                # Prepare response
                response = UserResponse(
                    first_name=user_data.first_name,
                    last_name=user_data.last_name,
                    email=user_data.email,
                    phone=user_data.phone,
                    country=user_data.country,
                    stytch_user_id=user_data.stytch_user_id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                print(f"Created user: {response}")
                return response

        # Run the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _create_user_sync)

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
                query = '''
                match
                $user isa user, has email "''' + email + '''";
                $user has first-name $first_name;
                $user has last-name $last_name;
                $user has email $email;
                $user has phone $phone;
                $user has country $country;
                $user has stytch-user-id $stytch_user_id;
                $user has created-at $created_at;
                $user has updated-at $updated_at;
                '''

                try:
                    print(f"Querying user with: {query}")
                    result = transaction.query(query).resolve()
                    answers = list(result)
                    
                    if answers:
                        # Extract data from the first answer
                        answer = answers[0]
                        concepts = answer.concepts()
                        
                        return UserResponse(
                            first_name=concepts['first_name'].as_attribute().get_value(),
                            last_name=concepts['last_name'].as_attribute().get_value(),
                            email=concepts['email'].as_attribute().get_value(),
                            phone=concepts['phone'].as_attribute().get_value(),
                            country=concepts['country'].as_attribute().get_value(),
                            stytch_user_id=concepts['stytch_user_id'].as_attribute().get_value(),
                            created_at=datetime.fromtimestamp(concepts['created_at'].as_attribute().get_value()),
                            updated_at=datetime.fromtimestamp(concepts['updated_at'].as_attribute().get_value())
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
                # First, find the user
                match_query = 'match $user isa user, has email "' + email + '";'
                
                # Build the delete and insert parts dynamically
                delete_parts = []
                insert_parts = []
                
                if update_data.first_name:
                    delete_parts.append('$user has first-name $old_first_name;')
                    insert_parts.append('$user has first-name "' + update_data.first_name + '";')
                if update_data.last_name:
                    delete_parts.append('$user has last-name $old_last_name;')
                    insert_parts.append('$user has last-name "' + update_data.last_name + '";')
                if update_data.phone:
                    delete_parts.append('$user has phone $old_phone;')
                    insert_parts.append('$user has phone "' + str(update_data.phone) + '";')
                if update_data.country:
                    delete_parts.append('$user has country $old_country;')
                    insert_parts.append('$user has country "' + update_data.country + '";')

                # Always update the updated-at timestamp
                delete_parts.append('$user has updated-at $old_updated_at;')
                insert_parts.append('$user has updated-at ' + str(int(datetime.utcnow().timestamp())) + ';')

                if delete_parts and insert_parts:
                    query = match_query + '\ndelete\n' + '\n'.join(delete_parts) + '\ninsert\n' + '\n'.join(insert_parts)
                    
                    try:
                        print(f"Updating user with query: {query}")
                        result = transaction.query(query).resolve()
                        print(f"User update result: {result}")
                        
                        # Return updated user
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
                query = '''
                match
                $user isa user, has email "''' + email + '''";
                delete
                $user isa user;
                '''

                try:
                    print(f"Deleting user with query: {query}")
                    result = transaction.query(query).resolve()
                    print(f"User deletion result: {result}")
                    return True
                except Exception as e:
                    print(f"Error deleting user: {e}")
                    return False

        # Run the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _delete_user_sync)
