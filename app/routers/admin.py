
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

from itsdangerous import URLSafeSerializer
from app.utils.auth import Hash

signer = URLSafeSerializer(settings.ADMIN_PASS, salt="admin-session")

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@router.post("/login", response_class=HTMLResponse)
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Check against MongoDB
    admin = await Admin.find_one(Admin.username == username)
    
    if admin and Hash.verify(password, admin.password):
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        
        # Create Signed Cookie
        session_token = signer.dumps({"user": admin.username})
        
        response.set_cookie(
            key=settings.SESSION_COOKIE, 
            value=session_token,
            max_age=settings.SESSION_EXPIRY,
            httponly=True,
            samesite="lax", # Strict can sometimes block redirects from external sites, Lax is okay for admin
            secure=True # Always secure for signed cookies
        )
        return response
    
    return RedirectResponse(url="/admin/login?error=Invalid+credentials", status_code=303)

@router.get("/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie(settings.SESSION_COOKIE)
    return response

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, is_admin: bool = Depends(get_current_admin), date: Optional[str] = Query(None)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    
    if date:
        try:
            # Parse requested date and set to IST
            target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=IST)
        except:
            target_date = datetime.now(IST)
    else:
        target_date = datetime.now(IST)

    # Calculate start and end of day in IST
    start_of_day_ist = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day_ist = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Convert to UTC for MongoDB Query (assuming DB stores naive UTC or aware UTC)
    # If DB stores naive UTC (default), we need to cast to UTC and strip tzinfo
    start_of_day_utc = start_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)
    end_of_day_utc = end_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)

    submissions = await Submission.find(
        Submission.created_at >= start_of_day_utc,
        Submission.created_at <= end_of_day_utc
    ).sort("-created_at").to_list()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "submissions": submissions,
        "selected_date": target_date.strftime("%Y-%m-%d")
    })

@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request, is_admin: bool = Depends(get_current_admin), success: Optional[str] = None):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    # Get the admin user (assuming single admin for now, or just get the first one)
    admin = await Admin.find_one()
    message = "Credentials updated successfully!" if success else None
    
    return templates.TemplateResponse("admin_settings.html", {"request": request, "admin": admin, "message": message})

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
        from app.utils.auth import Hash
        hashed_pw = Hash.bcrypt(password)
        
        admin.username = username
        admin.password = hashed_pw
        await admin.save()
        return RedirectResponse(url="/admin/settings?success=1", status_code=303)
    return RedirectResponse(url="/admin/dashboard")

@router.get("/edit/{id}", response_class=HTMLResponse)
async def edit_submission_page(request: Request, id: PydanticObjectId, success: Optional[str] = None, error: Optional[str] = None, is_admin: bool = Depends(get_current_admin)):
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
        "message": message,
        "error": error
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
         return RedirectResponse(url=f"/admin/edit/{id}?error=Invalid+registration+number+format.", status_code=303)

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

    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=IST)
        except:
            target_date = datetime.now(IST)
    else:
        target_date = datetime.now(IST)

    start_of_day_ist = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day_ist = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Convert to UTC
    start_of_day_utc = start_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)
    end_of_day_utc = end_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)

    submissions = await Submission.find(
        Submission.created_at >= start_of_day_utc,
        Submission.created_at <= end_of_day_utc
    ).to_list()
    
    # Adapt Beanie models to dict for Excel Service
    submissions_dicts = [s.dict() for s in submissions]
    
    # Get slots from MongoDB
    slot_times = await get_slot_times()
    
    from starlette.concurrency import run_in_threadpool
    
    # Run synchronous Pandas code in a thread pool to avoid blocking the event loop
    output = await run_in_threadpool(generate_excel_bytes, submissions_dicts, slot_times, target_date)
    
    filename = f"kabaddi_{target_date.day}_{target_date.month}_{target_date.year}.xlsx"
    return StreamingResponse(
        output, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
