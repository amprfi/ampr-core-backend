import asyncio
import uuid
from src.services.user_service import UserService
from src.models.user import UserCreate, UserUpdate
from pydantic import EmailStr

async def test_user_service():
    # Create a user service instance
    user_service = UserService()

    # Generate unique test data
    unique_id = str(uuid.uuid4())[:4]
    test_email = f"test-{unique_id}@example.org"
    test_user = UserCreate(
        first_name="John",
        last_name="Doe",
        email=test_email,
        phone=f"+12345678912",
        country="USA",
        stytch_user_id=f"stytch_{unique_id}"
    )

    # Test create_user
    print("Testing create_user...")
    try:
        created_user = await user_service.create_user(test_user)
        print(f"Created user: {created_user}")

        # Test get_user_by_email
        print("Testing get_user_by_email...")
        retrieved_user = await user_service.get_user_by_email(test_email)
        print(f"Retrieved user: {retrieved_user}")

        # Test update_user
        print("Testing update_user...")
        update_data = UserUpdate(
            first_name="Jane",
            last_name="Smith"
        )
        updated_user = await user_service.update_user(test_email, update_data)
        print(f"Updated user: {updated_user}")

        # Test delete_user
        print("Testing delete_user...")
        result = await user_service.delete_user(test_email)
        print(f"Delete result: {result}")

        # Verify deletion
        deleted_user = await user_service.get_user_by_email(test_email)
        print(f"User after deletion: {deleted_user}")

        print("All tests completed successfully!")

    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_user_service())