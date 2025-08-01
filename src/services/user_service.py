from typing import Optional
from datetime import datetime
from pydantic import EmailStr
from src.services.typedb_client import typedb_client
from typedb.driver import TransactionType
from src.services.auth_client import stytch_client
from src.models.user import UserCreate, UserResponse, UserUpdate
from contextlib import contextmanager

class UserService:
    def __init__(self):
        self.typedb = typedb_client

    def create_user(self, user_data: UserCreate) -> UserResponse:
        """
        Create a new user in TypeDB

        Args:
            user_data: UserCreate model with user data

        Returns:
            UserResponse model with created user data
        """
        with self.typedb.session() as session:
            with self.typedb.transaction(session) as transaction:
                # Build the insert query
                query = '''
                insert
                $user isa user,
                    has first-name $first_name,
                    has last-name $last_name,
                    has email $email,
                    has phone $phone,
                    has country $country,
                    has stytch-user-id $stytch_user_id,
                    has created-at $created_at,
                    has updated-at $updated_at;
                '''

                # Prepare the data
                data = {
                    'first_name': user_data.first_name,
                    'last_name': user_data.last_name,
                    'email': user_data.email,
                    'phone': user_data.phone,
                    'country': user_data.country,
                    'stytch_user_id': user_data.stytch_user_id,
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }

                # Execute the query
                response = transaction.query.insert(query, data)

                # Prepare response
                return UserResponse(
                    first_name=user_data.first_name,
                    last_name=user_data.last_name,
                    email=user_data.email,
                    phone=user_data.phone,
                    country=user_data.country,
                    stytch_user_id=user_data.stytch_user_id,
                    created_at=data['created_at'],
                    updated_at=data['updated_at']
                )

    def get_user_by_email(self, email: EmailStr) -> Optional[UserResponse]:
        """
        Get a user by email from TypeDB

        Args:
            email: User's email address

        Returns:
            UserResponse model if found, None otherwise
        """
        with self.typedb.session() as session:
            with self.typedb.transaction(session, TransactionType.READ) as transaction:
                query = '''
                match
                $user isa user, has email $email;
                get
                $user has first-name $first_name,
                $user has last-name $last_name,
                $user has email $email,
                $user has phone $phone,
                $user has country $country,
                $user has stytch-user-id $stytch_user_id,
                $user has created-at $created_at,
                $user has updated-at $updated_at;
                '''
                data = {'email': email}

                try:
                    response = transaction.query.match(query, data)
                    if response:
                        # Extract data from response
                        answer = response.get('answers')[0]
                        return UserResponse(
                            first_name=answer.get('first_name'),
                            last_name=answer.get('last_name'),
                            email=answer.get('email'),
                            phone=answer.get('phone'),
                            country=answer.get('country'),
                            stytch_user_id=answer.get('stytch_user_id'),
                            created_at=answer.get('created_at'),
                            updated_at=answer.get('updated_at')
                        )
                    return None
                except Exception as e:
                    print(f"Error getting user: {e}")
                    return None

    def update_user(self, email: EmailStr, update_data: UserUpdate) -> Optional[UserResponse]:
        """
        Update a user in TypeDB

        Args:
            email: User's email address
            update_data: UserUpdate model with fields to update

        Returns:
            Updated UserResponse model if successful, None otherwise
        """
        with self.typedb.session() as session:
            with self.typedb.transaction(session) as transaction:
                # Build the match part of the query
                match_query = 'match $user isa user, has email $email;'
                match_data = {'email': email}

                # Build the insert part dynamically based on what fields are provided
                updates = []
                data = {'email': email, 'updated_at': datetime.utcnow()}

                if update_data.first_name:
                    updates.append('$user has first-name $first_name;')
                    data['first_name'] = update_data.first_name
                if update_data.last_name:
                    updates.append('$user has last-name $last_name;')
                    data['last_name'] = update_data.last_name
                if update_data.phone:
                    updates.append('$user has phone $phone;')
                    data['phone'] = update_data.phone
                if update_data.country:
                    updates.append('$user has country $country;')
                    data['country'] = update_data.country

                # Add updated-at
                updates.append('$user has updated-at $updated_at;')

                if not updates:
                    return None  # Nothing to update

                insert_query = 'insert ' + ' '.join(updates)
                query = match_query + insert_query

                try:
                    # Execute the query
                    transaction.query.insert(query, data)

                    # Return the updated user
                    return self.get_user_by_email(email)
                except Exception as e:
                    print(f"Error updating user: {e}")
                    return None

    def delete_user(self, email: EmailStr) -> bool:
        """
        Delete a user from TypeDB

        Args:
            email: User's email address

        Returns:
            True if deletion was successful, False otherwise
        """
        with self.typedb.session() as session:
            with self.typedb.transaction(session) as transaction:
                query = '''
                match
                $user isa user, has email $email;
                delete
                $user isa user;
                '''
                data = {'email': email}

                try:
                    transaction.query.delete(query, data)
                    return True
                except Exception as e:
                    print(f"Error deleting user: {e}")
                    return False
