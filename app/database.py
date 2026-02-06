from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.config import settings
from app.models import Submission, Admin, Slot, AdminLog

async def init_db():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.DB_NAME], document_models=[Submission, Admin, Slot, AdminLog])
    
    # Bootstrap Admin if none exists
    if await Admin.count() == 0:
        print("[DB Init] Creating default admin user...")
        from app.utils.auth import Hash
        hashed_pw = Hash.bcrypt(settings.ADMIN_PASS)
        default_admin = Admin(username=settings.ADMIN_USER, password=hashed_pw)
        await default_admin.insert()
