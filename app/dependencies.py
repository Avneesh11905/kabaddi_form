
from fastapi import Cookie
from typing import Optional

def get_current_admin(admin_session: Optional[str] = Cookie(None)):
    if admin_session != "logged_in":
        return None
    return True
