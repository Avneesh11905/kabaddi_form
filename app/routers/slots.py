
from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from beanie import PydanticObjectId

from app.models import Slot
from app.dependencies import get_current_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Public API - Get all active slots
@router.get("/api/slots")
async def get_slots():
    slots = await Slot.find(Slot.is_active == True).to_list()
    return [{"id": str(s.id), "time": s.time} for s in slots]

# Admin Pages
@router.get("/admin/slots", response_class=HTMLResponse)
async def manage_slots_page(request: Request, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    slots = await Slot.find_all().to_list()
    return templates.TemplateResponse("manage_slots.html", {"request": request, "slots": slots})

@router.post("/admin/slots")
async def add_slot(time: str = Form(...), is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    # Check if slot with same time already exists
    existing = await Slot.find_one(Slot.time == time)
    if existing:
        # Slot already exists - just redirect back
        return RedirectResponse(url="/admin/slots?error=exists", status_code=303)
    
    new_slot = Slot(time=time)
    await new_slot.insert()
    return RedirectResponse(url="/admin/slots", status_code=303)

@router.post("/admin/slots/delete/{id}")
async def delete_slot(id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    slot = await Slot.get(id)
    if slot:
        await slot.delete()
    return RedirectResponse(url="/admin/slots", status_code=303)

@router.post("/admin/slots/toggle/{id}")
async def toggle_slot(id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    slot = await Slot.get(id)
    if slot:
        slot.is_active = not slot.is_active
        await slot.save()
    return RedirectResponse(url="/admin/slots", status_code=303)
