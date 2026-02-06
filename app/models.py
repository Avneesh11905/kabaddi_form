
from beanie import Document
from pydantic import Field, EmailStr
from datetime import datetime
from typing import List, Optional

class Submission(Document):
    reg_no: str
    email: EmailStr
    slots: List[str]
    edit_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    date_str: Optional[str] = None # Optional for backward compatibility with old records
    deleted_at: Optional[datetime] = None # For soft delete functionality

    class Settings:
        name = "submissions"
        indexes = [
            [
                ("reg_no", 1),
                ("date_str", 1)
            ],
            [("email", 1)]  # Index for search
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

class AdminLog(Document):
    log_type: str = "admin"  # "admin" for activity logs, "error" for error logs
    level: str = "INFO"  # INFO, WARNING, ERROR
    action: str  # e.g., "login", "logout", "edit", "delete", "download", "settings", "error"
    details: Optional[str] = None  # Additional context
    admin_username: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None  # Device/browser info
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "admin_logs"
        indexes = [
            [("created_at", -1)],  # Index for efficient pagination
            [("action", 1)],  # Index for filtering by action
            [("log_type", 1)],  # Index for filtering by log type
            [("level", 1)]  # Index for filtering by level
        ]


