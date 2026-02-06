
from fastapi import Cookie, HTTPException, status
from typing import Optional
from itsdangerous import URLSafeSerializer, BadSignature
from app.config import settings

signer = URLSafeSerializer(settings.ADMIN_PASS, salt="admin-session")

def get_current_admin(admin_session: Optional[str] = Cookie(None)):
    if not admin_session:
        return None
        
    try:
        data = signer.loads(admin_session)
        if not data or "user" not in data:
            return None
        return True
    except BadSignature:
        return None
