from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from pydantic_extra_types.phone_numbers import PhoneNumber


class UserCreate(BaseModel):
    """Model for creating a new user"""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: PhoneNumber
    gel_user_id: Optional[str] = Field(None, min_length=1, max_length=100)


class UserResponse(BaseModel):
    """Model for user API responses"""

    first_name: str
    last_name: str
    email: EmailStr
    phone: PhoneNumber
    stytch_user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserUpdate(BaseModel):
    """Model for updating user data"""

    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[PhoneNumber] = None
    gel_user_id: Optional[str] = Field(None, min_length=1, max_length=100)
