
from fastapi import APIRouter, Request, Form, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import re
from datetime import datetime
from typing import List, Optional
from beanie import PydanticObjectId
from app.models import Submission, Slot
from app.config import settings
from app.services.email_service import send_acknowledgement_email

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def read_form(
    request: Request, 
    error: Optional[str] = None,
    reg_no: Optional[str] = None,
    email: Optional[str] = None,
    selected_slots: Optional[List[str]] = Query(None)
):
    context = {
        "request": request, 
        "error": error,
        "reg_no": reg_no,
        "email": email
    }
    # If selected_slots are passed back, mark them as checked in the template logic 
    # (The template iterates slots. We need to check if slot in selected_slots)
    # Actually, the template uses `if slot in submission.slots`. 
    # We can pass a dummy object or just modify the template to use a list directly?
    # Simplified: The template usually checks specific variables if we pass them.
    # Let's check index.html: `{% for slot in slots %}` ... `value="{{ slot }}"` ...
    # We don't have existing logic to pre-fill checkboxes from `selected_slots` variable in the template *unless* we added it?
    # The previous `render_error` passed `selected_slots` implicitly? No, previous `render_error` only passed `reg_no` and `email`?
    # Looking at previous step 290: `render_error` passed `reg_no` and `email`. It did NOT pass `selected_slots` back to the template context explicitly to re-check them. 
    # So previously, if you errored, your checkboxes were cleared. 
    # I will stick to that behavior for simplicity unless specifically asked, but adding it is better.
    # Let's just pass `reg_no` and `email` as before to be safe.
    
    return templates.TemplateResponse("index.html", context)

@router.get("/submitted/{id}", response_class=HTMLResponse)
async def read_submitted(request: Request, id: PydanticObjectId):
    return templates.TemplateResponse("submitted.html", {"request": request, "submission_id": str(id)})

@router.post("/", response_class=HTMLResponse)
async def submit_form(
    request: Request, 
    reg_no: str = Form(""), 
    email: str = Form(""),
    selected_slots: List[str] = Form([])
):
    def redirect_with_error(msg, passed_reg_no=reg_no, passed_email=email):
        import urllib.parse
        params = {"error": msg}
        if passed_reg_no:
            params["reg_no"] = passed_reg_no
        if passed_email:
            params["email"] = passed_email
        
        # We don't preserve slots to keep URL clean, matching previous behavior
        query_string = urllib.parse.urlencode(params)
        return RedirectResponse(url=f"/?{query_string}", status_code=303)

    try:
        if not reg_no:
            return redirect_with_error("Registration Number is required")
        
        if not selected_slots:
            return redirect_with_error("Select at least one slot")
        
        # Validation: Ensure all selected slots are valid active slots
        # We fetch all active slots and check if selected_slots is a subset
        active_slots_docs = await Slot.find(Slot.is_active == True).to_list()
        active_slot_times = {s.time for s in active_slots_docs}
        
        # Check if any selected slot is NOT in active slots
        invalid_slots = [s for s in selected_slots if s not in active_slot_times]
        if invalid_slots:
            return redirect_with_error("Invalid slots selected. Please refresh and try again.")
            
        # Auto-convert to uppercase
        reg_no = reg_no.upper()
        
        reg_pattern = r"^\d{2}[A-Z]{3}\d{5}$"
        if not re.match(reg_pattern, reg_no):
            return redirect_with_error("Invalid format. Example: 23BAI10056", reg_no)

        # Duplicate Check Logic (Day Specific)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        duplicate = await Submission.find_one(
            Submission.reg_no == reg_no,
            Submission.created_at >= today_start
        )
        
        if duplicate:
            return redirect_with_error("This registration number has submitted a response for today. Contact admin for new response.", reg_no)

        # Save to MongoDB
        if not email:
            return redirect_with_error("Email is required")
        
        if not email.endswith("@vitbhopal.ac.in"):
             return redirect_with_error("Email must be a VIT Bhopal email (@vitbhopal.ac.in)")
            
        submission_data = {
            "reg_no": reg_no,
            "slots": selected_slots,
            "email": email
        }
            
        submission = Submission(**submission_data)
        await submission.insert()
        
        # Send Email if provided
        if email:
            # Ensure no double slashes if APP_URL has trailing slash
            base_url = settings.APP_URL.rstrip("/")
            edit_link = f"{base_url}/edit/{str(submission.id)}"
            send_acknowledgement_email(email, reg_no, selected_slots, edit_link)

        # Redirect to submitted page
        return RedirectResponse(url=f"/submitted/{submission.id}", status_code=303)

    except Exception as e:
        print(f"Internal Error: {e}")
        return redirect_with_error("Internal Server Error")

@router.get("/edit/{id}", response_class=HTMLResponse)
async def user_edit_page(request: Request, id: PydanticObjectId, success: Optional[str] = None, no_change: Optional[str] = None):
    submission = await Submission.get(id)
    if not submission:
        return RedirectResponse(url="/?error=Submission+not+found.+It+may+have+been+deleted.", status_code=303)
    
    message = None
    if success:
        message = "Submission updated successfully!"
    elif no_change:
        message = "No changes detected. Your submission remains unchanged."
        
    return templates.TemplateResponse("user_edit.html", {
        "request": request,
        "submission": submission,
        "id": str(id),
        "message": message,
        "is_no_change": bool(no_change)
    })

@router.post("/edit/{id}", response_class=HTMLResponse)
async def user_update_submission(
    request: Request, 
    id: PydanticObjectId, 
    email: str = Form(...),
    selected_slots: List[str] = Form(...),
):
    if not email.endswith("@vitbhopal.ac.in"):
         submission = await Submission.get(id)
         if submission:
             return templates.TemplateResponse("user_edit.html", {
                "request": request, 
                "submission": submission,
                "id": str(id),
                "error": "Email must be a VIT Bhopal email (@vitbhopal.ac.in)"
            })
         return RedirectResponse(url="/")
    submission = await Submission.get(id)
    if not submission:
        # Submission was deleted - redirect to home with error
        return RedirectResponse(url="/?error=Submission+not+found.+It+may+have+been+deleted.", status_code=303)

    # Validation: Ensure all selected slots are valid active slots
    active_slots_docs = await Slot.find(Slot.is_active == True).to_list()
    active_slot_times = {s.time for s in active_slots_docs}
    
    # Check if any selected slot is NOT in active slots
    invalid_slots = [s for s in selected_slots if s not in active_slot_times]
    if invalid_slots:
        return templates.TemplateResponse("user_edit.html", {
            "request": request,
            "submission": submission,
            "id": str(id),
            "error": "Invalid slots selected. Please refresh and try again."
        })
    
    # Check edit limit
    if submission.edit_count >= 3:
        return templates.TemplateResponse("user_edit.html", {
            "request": request,
            "submission": submission,
            "id": str(id),
            "error": "You have reached the maximum number of edits (3). Please contact admin for further changes."
        })
    
    # Compare old and new values (normalize slots for comparison)
    old_email = submission.email or ""
    old_slots = set(submission.slots)
    new_slots = set(selected_slots)
    
    has_changes = (old_email != email) or (old_slots != new_slots)
    
    if not has_changes:
        # No changes made - redirect with no_change flag
        return RedirectResponse(url=f"/edit/{id}?no_change=1", status_code=303)

    # Update fields
    submission.email = email
    submission.slots = selected_slots
    submission.edit_count += 1
    await submission.save()
    
    if submission.email:
        from app.services.email_service import send_update_email
        edits_remaining = 3 - submission.edit_count
        edit_link = f"{settings.APP_URL}/edit/{id}"
        send_update_email(submission.email, submission.reg_no, submission.slots, edits_remaining, edit_link)
    
    # PRG Pattern: Redirect to prevent form resubmission on refresh
    return RedirectResponse(url=f"/edit/{id}?success=1", status_code=303)
