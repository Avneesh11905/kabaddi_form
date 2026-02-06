
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
from app.models import Submission, Admin, Slot, AdminLog

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

async def log_admin_action(request: Request, action: str, details: str = None, admin_username: str = None, log_type: str = "admin", level: str = None):
    """Log admin activity or errors to MongoDB"""
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Auto-detect level if not provided
    if level is None:
        if action == "login_failed":
            level = "WARNING"
        elif action == "error" or log_type == "error":
            level = "ERROR"
        else:
            level = "INFO"
    
    log = AdminLog(
        log_type=log_type,
        level=level,
        action=action,
        details=details,
        admin_username=admin_username,
        ip_address=ip_address,
        user_agent=user_agent
    )
    await log.insert()

async def log_error(request: Request, error_message: str, details: str = None):
    """Convenience function to log errors"""
    await log_admin_action(request, "error", error_message if details is None else f"{error_message}: {details}", log_type="error", level="ERROR")

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
        await log_admin_action(request, "login", f"Login successful", admin.username)
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
    
    await log_admin_action(request, "login_failed", f"Failed login attempt for username: {username}")
    return RedirectResponse(url="/admin/login?error=Invalid+credentials", status_code=303)

@router.get("/logout")
async def admin_logout(request: Request):
    await log_admin_action(request, "logout", "Admin logged out")
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie(settings.SESSION_COOKIE)
    return response

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request, 
    is_admin: bool = Depends(get_current_admin), 
    date: Optional[str] = Query(None), 
    search: Optional[str] = Query(None),
    view: str = Query("active")
):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    
    target_date = datetime.now(IST) # Default needed for template even if searching
    
    # Criteria list for query
    criteria = []
    
    # 1. Filter by View (Trash vs Active)
    if view == "trash":
        criteria.append(Submission.deleted_at != None)
    else:
        criteria.append(Submission.deleted_at == None) # Default to active only

    # 2. Filter by Search OR Date
    if search:
        # Search by email (case-insensitive) - Prefix match
        import re
        escaped_search = re.escape(search)
        criteria.append({"email": {"$regex": f"^{escaped_search}", "$options": "i"}})
        
        # When searching, we typically ignore date to allow finding records from past
        # So we don't add date criteria here
                
    else:
        # Date-based filtering (only if no search)
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

        # Convert to UTC for MongoDB Query
        start_of_day_utc = start_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)
        end_of_day_utc = end_of_day_ist.astimezone(timezone.utc).replace(tzinfo=None)

        criteria.append(Submission.created_at >= start_of_day_utc)
        criteria.append(Submission.created_at <= end_of_day_utc)
    
    # Execute Query
    submissions = await Submission.find(*criteria).sort("-created_at").to_list()
    
    # Convert created_at from UTC to IST for display
    for sub in submissions:
        if sub.created_at:
            # MongoDB returns naive UTC, convert to IST
            utc_time = sub.created_at.replace(tzinfo=timezone.utc)
            sub.created_at = utc_time.astimezone(IST)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "submissions": submissions,
        "selected_date": target_date.strftime("%Y-%m-%d"),
        "search_query": search or "",
        "current_view": view
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
    password: Optional[str] = Form(None),
    is_admin: bool = Depends(get_current_admin)
):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    admin = await Admin.find_one()
    if admin:
        # Update username
        admin.username = username
        
        # Update password only if provided
        if password:
            from app.utils.auth import Hash
            hashed_pw = Hash.bcrypt(password)
            admin.password = hashed_pw
            
        await admin.save()
        
        await log_admin_action(request, "settings", f"Updated admin settings (username: {username})")
        
        # Update session cookie with new username
        response = RedirectResponse(url="/admin/settings?success=1", status_code=303)
        session_token = signer.dumps({"user": admin.username})
        response.set_cookie(
            key=settings.SESSION_COOKIE, 
            value=session_token,
            max_age=settings.SESSION_EXPIRY,
            httponly=True,
            samesite="lax",
            secure=True
        )
        return response
        
    return RedirectResponse(url="/admin/dashboard")

@router.get("/edit/{id}", response_class=HTMLResponse)
async def edit_submission_page(request: Request, id: PydanticObjectId, success: Optional[str] = None, error: Optional[str] = None, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if not submission:
         return RedirectResponse(url="/admin/dashboard")
    
    # Convert created_at from UTC to IST for display
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    if submission.created_at:
        utc_time = submission.created_at.replace(tzinfo=timezone.utc)
        submission.created_at = utc_time.astimezone(IST)
    
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
    
    await log_admin_action(request, "edit", f"Edited submission {id} (reg_no: {reg_no})")
        
    # PRG Pattern: Redirect to prevent resubmission
    return RedirectResponse(url=f"/admin/edit/{id}?success=1", status_code=303)

@router.post("/delete/{id}")
async def delete_submission(request: Request, id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if submission:
        reg_no = submission.reg_no
        # Soft delete
        submission.deleted_at = datetime.utcnow()
        await submission.save()
        await log_admin_action(request, "delete", f"Soft deleted submission (reg_no: {reg_no})")
        
    return RedirectResponse(url="/admin/dashboard?view=active", status_code=303)

@router.post("/restore/{id}")
async def restore_submission(request: Request, id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if submission:
        reg_no = submission.reg_no
        # Restore
        submission.deleted_at = None
        await submission.save()
        await log_admin_action(request, "restore", f"Restored submission (reg_no: {reg_no})")
        
    return RedirectResponse(url="/admin/dashboard?view=trash", status_code=303)

@router.get("/download")
async def download_excel(request: Request, is_admin: bool = Depends(get_current_admin), date: Optional[str] = Query(None)):
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

    # Filter by date/time (UTC)
    criteria = [
        Submission.created_at >= start_of_day_utc,
        Submission.created_at <= end_of_day_utc,
        Submission.deleted_at == None  # Exclude soft deleted items
    ]

    submissions = await Submission.find(*criteria).to_list()
    
    await log_admin_action(request, "download", f"Downloaded Excel for {target_date.strftime('%Y-%m-%d')} ({len(submissions)} submissions)")
    
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

@router.post("/delete/hard/{id}")
async def hard_delete_submission(request: Request, id: PydanticObjectId, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    submission = await Submission.get(id)
    if submission:
        reg_no = submission.reg_no
        # Hard delete - remove from DB entirely
        await submission.delete()
        await log_admin_action(request, "hard_delete", f"Permanently deleted submission (reg_no: {reg_no})")
        
    return RedirectResponse(url="/admin/dashboard?view=trash", status_code=303)

@router.post("/trash/empty")
async def empty_trash(request: Request, is_admin: bool = Depends(get_current_admin)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    # Find all items in trash
    trash_items = await Submission.find(Submission.deleted_at != None).to_list()
    count = len(trash_items)
    
    if count > 0:
        # Delete them all
        await Submission.find(Submission.deleted_at != None).delete()
        await log_admin_action(request, "empty_trash", f"Permanently deleted {count} items from trash")
        
    return RedirectResponse(url="/admin/dashboard?view=trash", status_code=303)

@router.get("/logs", response_class=HTMLResponse)
async def admin_logs_page(request: Request, is_admin: bool = Depends(get_current_admin), page: int = Query(1, ge=1), filter: Optional[str] = Query(None), level: Optional[str] = Query(None)):
    if not is_admin:
        return RedirectResponse(url="/admin/login")
    
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    
    # Define action categories
    action_categories = {
        "auth": ["login", "login_failed", "logout"],
        "data": ["edit", "delete", "download"],
        "system": ["settings"]
    }
    
    per_page = 20
    skip = (page - 1) * per_page
    
    # Build query based on filter and level
    query_filter = {}
    
    if filter == "errors":
        query_filter["log_type"] = "error"
    elif filter and filter in action_categories:
        query_filter["action"] = {"$in": action_categories[filter]}
    
    if level and level in ["INFO", "WARNING", "ERROR"]:
        query_filter["level"] = level
    
    query = AdminLog.find(query_filter) if query_filter else AdminLog.find()
    
    # Get total count for pagination
    total_logs = await query.count()
    total_pages = max(1, (total_logs + per_page - 1) // per_page)  # Ceiling division, min 1
    
    # Fetch logs with pagination, sorted by newest first
    logs = await query.sort("-created_at").skip(skip).limit(per_page).to_list()
    
    # Convert timestamps to IST for display
    for log in logs:
        if log.created_at:
            utc_time = log.created_at.replace(tzinfo=timezone.utc)
            log.created_at = utc_time.astimezone(IST)
    
    return templates.TemplateResponse("admin_logs.html", {
        "request": request,
        "logs": logs,
        "current_page": page,
        "total_pages": total_pages,
        "total_logs": total_logs,
        "current_filter": filter or "all",
        "current_level": level or "all"
    })
