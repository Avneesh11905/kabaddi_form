from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.database import init_db
from app.routers import form, admin, slots

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(form.router)
app.include_router(admin.router)
app.include_router(slots.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app='main:app', host="0.0.0.0", port=8000, reload=True)
