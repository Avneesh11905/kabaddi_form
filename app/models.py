
from beanie import Document
from pydantic import Field, EmailStr
from datetime import datetime
from typing import List, Optional

class Submission(Document):
    reg_no: str
    email: EmailStr
    slots: List[str]
    edit_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    date_str: Optional[str] = None # Optional for backward compatibility with old records

    class Settings:
        name = "submissions"
        indexes = [
            [
                ("reg_no", 1),
                ("date_str", 1)
            ]
        ]

class Admin(Document):
    username: str
    password: str

    class Settings:
        name = "admins"

class Slot(Document):
    time: str
    is_active: bool = True

    class Settings:
        name = "slots"
