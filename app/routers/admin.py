
from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from datetime import datetime
from typing import List, Optional
from beanie import PydanticObjectId
import re

from app.config import settings
from app.dependencies import get_current_admin
from app.services.excel_service import generate_excel_bytes
from app.models import Submission, Admin, Slot

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

async def get_slot_times():
    """Fetch active slot times from MongoDB"""
    slots = await Slot.find(Slot.is_active == True).to_list()
    return [s.time for s in slots]

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Check against MongoDB
    admin = await Admin.find_one(Admin.username == username)
    
    if admin and admin.password == password:
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(
            key=settings.SESSION_COOKIE, 
            value="logged_in",
            max_age=settings.SESSION_EXPIRY,
            httponly=True,
            samesite="strict"
        )
        return response
    
    # Fallback to config creds ONLY if DB is somehow empty (edge case), but DB init handles bootstrap.
    # So we strictly use DB.
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@router.get("/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie(settings.SESSION_COOKIE)
    return response

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, is_admin: bool = Depends(get_current_admin), date: Optional[str] = Query(None)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except:
            target_date = datetime.now()
    else:
        target_date = datetime.now()

    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    submissions = await Submission.find(
        Submission.created_at >= start_of_day,
        Submission.created_at <= end_of_day
    ).sort("-created_at").to_list()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "submissions": submissions,
        "selected_date": target_date.strftime("%Y-%m-%d")
    })

@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    # Get the admin user (assuming single admin for now, or just get the first one)
    admin = await Admin.find_one()
    return templates.TemplateResponse("admin_settings.html", {"request": request, "admin": admin})

@router.post("/settings", response_class=HTMLResponse)
async def update_admin_settings(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    is_admin: bool = Depends(get_current_admin)
):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    admin = await Admin.find_one()
    if admin:
        admin.username = username
        admin.password = password
        await admin.save()
        return templates.TemplateResponse("admin_settings.html", {
            "request": request, 
            "admin": admin,
            "message": "Credentials updated successfully!"
        })
    return RedirectResponse(url="/admin/dashboard")

@router.get("/edit/{id}", response_class=HTMLResponse)
async def edit_submission_page(request: Request, id: PydanticObjectId, success: Optional[str] = None, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if not submission:
         return RedirectResponse(url="/admin/dashboard")
    
    message = "Submission updated successfully!" if success else None

    return templates.TemplateResponse("edit.html", {
        "request": request, 
        "submission": submission,
        "id": str(id),
        "message": message
    })

@router.post("/edit/{id}")
async def edit_submission(
    request: Request, 
    id: PydanticObjectId, 
    reg_no: str = Form(...), 
    email: str = Form(""),
    selected_slots: List[str] = Form(...), 
    is_admin: bool = Depends(get_current_admin)
):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    reg_no = reg_no.upper()
    
    reg_pattern = r"^\d{2}[A-Z]{3}\d{5}$"
    if not re.match(reg_pattern, reg_no):
         # Create a fake submission-like dict for template rendering
         fake_submission = type('obj', (object,), {
             'reg_no': reg_no,
             'slots': selected_slots,
             'email': email
         })()
         return templates.TemplateResponse("edit.html", {
            "request": request, 
            "submission": fake_submission,
            "id": str(id),
            "error": "Invalid registration number format."
        })

    submission = await Submission.get(id)
    if not submission:
        # Submission was deleted - redirect to dashboard
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    
    submission.reg_no = reg_no
    submission.email = email
    submission.slots = selected_slots
    await submission.save()
        
    # PRG Pattern: Redirect to prevent resubmission
    return RedirectResponse(url=f"/admin/edit/{id}?success=1", status_code=303)

@router.post("/delete/{id}")
async def delete_submission(id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if submission:
        await submission.delete()
        
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@router.get("/download")
async def download_excel(is_admin: bool = Depends(get_current_admin), date: Optional[str] = Query(None)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except:
            target_date = datetime.now()
    else:
        target_date = datetime.now()

    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    submissions = await Submission.find(
        Submission.created_at >= start_of_day,
        Submission.created_at <= end_of_day
    ).to_list()
    
    # Adapt Beanie models to dict for Excel Service
    submissions_dicts = [s.dict() for s in submissions]
    
    # Get slots from MongoDB
    slot_times = await get_slot_times()
    
    output = generate_excel_bytes(submissions_dicts, slot_times, target_date)
    
    filename = f"kabaddi_{target_date.day}_{target_date.month}_{target_date.year}.xlsx"
    return StreamingResponse(
        output, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
