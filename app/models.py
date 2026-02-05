
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

    class Settings:
        name = "submissions"

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
