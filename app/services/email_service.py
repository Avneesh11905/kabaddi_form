
import resend
from app.config import settings

resend.api_key = settings.RESEND_API_KEY

def send_acknowledgement_email(email: str, reg_no: str, slots: list[str], edit_link: str):
    if not settings.RESEND_API_KEY:
        print("[Email Service] Resend API Key is MISSING or Empty.")
        return

    print(f"[Email Service] Attempting to send email to {email}...")
    
    try:
        html_content = f"""
        <h1>Kabaddi On-Duty Slot Submission Received</h1>
        <p>Registration Number: <strong>{reg_no}</strong></p>
        <p>Selected Slots: {', '.join(slots)}</p>
        <p>You can edit your submission here: <a href="{edit_link}">Edit Submission</a></p>
        """
        
        # Sender updated to custom domain
        r = resend.Emails.send({
            "from": "Kabaddi OD Form <no-reply@aymahajan.in>",
            "to": email,
            "subject": "On-Duty Slot Submission Received",
            "html": html_content
        })
        print(f"[Email Service] Resend API Response: {r}")
        
    except Exception as e:
        print(f"[Email Service] FAILED to send email: {str(e)}")

def send_update_email(email: str, reg_no: str, slots: list[str], edits_remaining: int, edit_link: str):
    if not settings.RESEND_API_KEY:
        print("[Email Service] Resend API Key is MISSING or Empty.")
        return

    print(f"[Email Service] Attempting to send update email to {email}...")
    
    try:
        edits_text = f"You have <strong>{edits_remaining}</strong> edit(s) remaining." if edits_remaining > 0 else "<strong>You have used all your edits.</strong> Contact admin for further changes."
        
        html_content = f"""
        <h1>Kabaddi Submission Updated</h1>
        <p>Your submission for <strong>{reg_no}</strong> has been updated.</p>
        <p><strong>New Selected Slots:</strong> {', '.join(slots)}</p>
        <p style="margin-top: 16px; padding: 12px; background: #f0f4f8; border-radius: 8px;">{edits_text}</p>
        <p style="margin-top: 16px;">Need to make changes? <a href="{edit_link}" style="color: #2563eb; font-weight: 600;">Edit your submission</a></p>
        """
        
        r = resend.Emails.send({
            "from": "Kabaddi OD Form <no-reply@aymahajan.in>",
            "to": email,
            "subject": "Submission Updated Successfully",
            "html": html_content
        })
        print(f"[Email Service] Update Email Response: {r}")
        
    except Exception as e:
        print(f"[Email Service] FAILED to send update email: {str(e)}")
