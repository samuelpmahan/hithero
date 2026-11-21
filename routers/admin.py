"""Admin-only tools: teacher report, account deletion, new admin accounts."""

import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_admin
from db import get_db
from ratelimit import limiter
from repositories import teachers, users
from services import accounts

router = APIRouter()


@router.post("/admin/generate_teacher_report/")
async def generate_teacher_report(state: str = Form(...), county: str = Form(None), district: str = Form(None), school: str = Form(None), caller: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    # Step 1: Dynamically filter TeacherList based on provided fields (excluding regUserID)
    report_teachers = teachers.report_rows(db, state, county, district, school)

    if not report_teachers:
        raise HTTPException(status_code=404, detail="No teachers found with the specified criteria.")

    # Step 2: Fetch email and phone from RegisteredUsers using regUserID
    reg_user_ids = [teacher.regUserID for teacher in report_teachers]
    contacts = users.contacts_by_id(db, reg_user_ids)

    # Step 3: Map teachers to their corresponding user data (email and phone)
    user_dict = {c.id: {"email": c.email, "phone": c.phone_number} for c in contacts}

    table_data = [["Name", "School", "Email", "Phone"]]
    for teacher in report_teachers:
        table_data.append([
            teacher.name or "",
            teacher.school or "",
            user_dict.get(teacher.regUserID, {}).get('email', 'N/A'),
            user_dict.get(teacher.regUserID, {}).get('phone', 'N/A'),
        ])

    # Step 4: Build the PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph("Teacher Report", styles['Title']), Spacer(1, 12)]

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)

    # Step 5: Stream the PDF back to the browser as a download
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=teacher_report.pdf"}
    )



        
@router.post("/profile/delete/")
async def admin_delete_user_account(target_email: str = Form(...), admin_secret_input: str = Form(...), user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Allows an authenticated 'admin' user to delete *any* user account 
    by providing the target user's email and a secret key via form submission.
    Deletes the associated teacher entry and the registered user account.
    """
    accounts.check_admin_secret(admin_secret_input)
    accounts.delete_account(db, target_email)
    return {"message": f"Successfully deleted account and associated data for target user: {target_email}."}


@router.post("/admin/create_admin/")
@limiter.limit("5/minute")
async def create_admin_account(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    admin_secret_input: str = Form(...),
    user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    """
    Allows an authenticated 'admin' user, who also supplies the server's admin
    secret, to create a brand new admin account directly in registered_users.
    Only email, password, and role are stored; id is auto-assigned by the DB.
    """
    accounts.check_admin_secret(admin_secret_input)
    accounts.check_new_admin_password(password, confirm_password)
    accounts.create_admin(db, email, password)
    return {"message": f"Admin account created successfully for {email}."}
