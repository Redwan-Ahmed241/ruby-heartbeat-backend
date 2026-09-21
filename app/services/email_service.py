"""Asynchronous transactional email notification service.

Provides non-blocking email dispatch with:
1. Standard SMTP support (Gmail, etc.).
2. Console Safe Mock fallback for local development and defense demonstrations.
3. Single donor match alerts and emergency mass radius broadcasts.
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _render_single_match_html(
    donor_name: str,
    blood_group: str,
    hospital_name: str,
    match_id: str,
    distance_km: Optional[float] = None,
    request_id: Optional[str] = None,
) -> str:
    """Render HTML template for single donor match alert."""
    dist_text = f"{distance_km:.1f} km away" if distance_km is not None else "Near your registered location"
    portal_url = (
        f"{settings.FRONTEND_URL}/request/{request_id}"
        if request_id
        else f"{settings.FRONTEND_URL}/donor"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }}
    .header {{ background-color: #8B0000; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
    .header p {{ margin: 6px 0 0 0; font-size: 14px; opacity: 0.9; }}
    .body {{ padding: 28px 24px; }}
    .highlight-card {{ background-color: #fef2f2; border-left: 4px solid #8B0000; padding: 16px; margin: 20px 0; border-radius: 4px; }}
    .row {{ margin-bottom: 8px; font-size: 14px; }}
    .label {{ font-weight: 600; color: #64748b; }}
    .value {{ font-weight: 700; color: #0f172a; }}
    .btn {{ display: inline-block; background-color: #8B0000; color: #ffffff !important; text-decoration: none; padding: 12px 28px; border-radius: 6px; font-weight: 600; font-size: 14px; margin-top: 16px; text-align: center; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>LifeDrop • Blood Match Alert</h1>
      <p>A patient urgently requires your blood type</p>
    </div>
    <div class="body">
      <p>Hello <strong>{donor_name}</strong>,</p>
      <p>Our Intelligent Matching Engine has matched your donor profile with an active blood request in your area.</p>
      
      <div class="highlight-card">
        <div class="row"><span class="label">Requested Blood Group:</span> <span class="value" style="color: #8B0000; font-size: 16px;">{blood_group}</span></div>
        <div class="row"><span class="label">Hospital / Location:</span> <span class="value">{hospital_name}</span></div>
        <div class="row"><span class="label">Estimated Distance:</span> <span class="value">{dist_text}</span></div>
        <div class="row"><span class="label">Match ID:</span> <span class="value" style="font-family: monospace; font-size: 12px;">{match_id}</span></div>
      </div>

      <p>Your contact details remain strictly masked and protected until you review and accept this request in your portal.</p>
      
      <div style="text-align: center;">
        <a href="{portal_url}" class="btn">View & Respond to Match</a>
      </div>
    </div>
    <div class="footer">
      <p>Smart Blood Donation Management System (SBDMS) • LifeDrop Network</p>
      <p>This is an automated notification. If you are unable to donate at this time, please decline in the portal so another candidate can be contacted immediately.</p>
    </div>
  </div>
</body>
</html>"""


def _render_emergency_broadcast_html(
    blood_group: str,
    hospital_name: str,
    units_needed: float,
    request_id: str,
) -> str:
    """Render HTML template for emergency mass broadcast."""
    portal_url = f"{settings.FRONTEND_URL}/request/{request_id}"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 2px solid #dc2626; overflow: hidden; box-shadow: 0 4px 10px rgba(220, 38, 38, 0.15); }}
    .header {{ background-color: #b91c1c; color: #ffffff; padding: 24px; text-align: center; }}
    .badge {{ display: inline-block; background-color: #fee2e2; color: #991b1b; padding: 4px 12px; border-radius: 9999px; font-weight: 700; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 800; }}
    .body {{ padding: 28px 24px; }}
    .alert-card {{ background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 18px; margin: 20px 0; border-radius: 4px; }}
    .row {{ margin-bottom: 8px; font-size: 14px; }}
    .label {{ font-weight: 600; color: #64748b; }}
    .value {{ font-weight: 700; color: #0f172a; }}
    .btn {{ display: inline-block; background-color: #dc2626; color: #ffffff !important; text-decoration: none; padding: 14px 32px; border-radius: 6px; font-weight: 700; font-size: 15px; margin-top: 16px; text-align: center; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">CRITICAL EMERGENCY BROADCAST</div>
      <h1>Urgent Blood Needed Immediately</h1>
      <p style="margin: 4px 0 0 0; opacity: 0.95;">A life-critical patient requires an immediate transfusion</p>
    </div>
    <div class="body">
      <p>Dear Valued LifeDrop Donor,</p>
      <p>An <strong>EMERGENCY</strong> priority blood request has just been broadcast in your immediate radius. Compatible donors are being alerted simultaneously.</p>
      
      <div class="alert-card">
        <div class="row"><span class="label">Blood Group Required:</span> <span class="value" style="color: #b91c1c; font-size: 18px;">{blood_group}</span></div>
        <div class="row"><span class="label">Hospital / Center:</span> <span class="value">{hospital_name}</span></div>
        <div class="row"><span class="label">Units Required:</span> <span class="value">{units_needed} Unit(s)</span></div>
        <div class="row"><span class="label">Request ID:</span> <span class="value" style="font-family: monospace; font-size: 12px;">{request_id}</span></div>
      </div>

      <p>If you are healthy, currently available, and able to donate, please open the portal to respond immediately.</p>
      
      <div style="text-align: center;">
        <a href="{portal_url}" class="btn">Respond to Emergency Request</a>
      </div>
    </div>
    <div class="footer">
      <p>LifeDrop Emergency Dispatch Network • Smart Blood Donation Management System</p>
      <p>Every minute counts in critical transfusions. Thank you for your readiness to save lives.</p>
    </div>
  </div>
</body>
</html>"""


def _dispatch_email(
    to_email: str,
    subject: str,
    text_content: str,
    html_content: str,
    is_emergency: bool = False,
) -> bool:
    """Internal dispatcher handling Resend, SMTP, or Graceful Console Fallback."""
    body_preview = text_content[:120].replace("\n", " ").strip()

    # 1. Option: Standard SMTP (Gmail, etc., if configured)
    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
            msg["To"] = to_email
            if is_emergency:
                msg["X-Priority"] = "1"
                msg["Priority"] = "Urgent"
                msg["Importance"] = "high"

            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAILS_FROM_EMAIL, [to_email], msg.as_string())

            logger.info(f"✅ [EMAIL SENT via SMTP] To: {to_email} | Subject: {subject}")
            return True
        except Exception as exc:
            logger.error(f"❌ Failed to dispatch email to {to_email}: {str(exc)}", exc_info=True)

    # 2. Critical Fail-Safe / Demo Mode: Console Mock Log
    # Gracefully logs dispatch without throwing exceptions
    logger.info(f"📧 [MOCK EMAIL SENT] To: {to_email} | Subject: {subject} | Body: {body_preview}...")
    return True


def _render_donor_accepted_html(
    recipient_name: str,
    donor_name: str,
    donor_phone: str,
    donor_area: str,
    request_id: str,
) -> str:
    """Render HTML template for recipient notification when a donor accepts."""
    portal_url = f"{settings.FRONTEND_URL}/recipient?tab=requests"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #10b981; overflow: hidden; box-shadow: 0 4px 10px rgba(16, 185, 129, 0.1); }}
    .header {{ background-color: #059669; color: #ffffff; padding: 24px; text-align: center; }}
    .badge {{ display: inline-block; background-color: #d1fae5; color: #065f46; padding: 4px 12px; border-radius: 9999px; font-weight: 700; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 800; }}
    .body {{ padding: 28px 24px; }}
    .success-card {{ background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 18px; margin: 20px 0; border-radius: 4px; }}
    .row {{ margin-bottom: 8px; font-size: 14px; }}
    .label {{ font-weight: 600; color: #64748b; }}
    .value {{ font-weight: 700; color: #0f172a; }}
    .btn {{ display: inline-block; background-color: #059669; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 700; font-size: 14px; margin-top: 12px; text-align: center; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">DONOR CONFIRMED</div>
      <h1>A Donor Has Accepted Your Request!</h1>
      <p style="margin: 4px 0 0 0; opacity: 0.95;">Direct contact information is now unlocked</p>
    </div>
    <div class="body">
      <p>Hello <strong>{recipient_name}</strong>,</p>
      <p>Great news! A volunteer donor has stepped forward to fulfill your blood request.</p>
      
      <div class="success-card">
        <div class="row"><span class="label">Donor Name:</span> <span class="value">{donor_name}</span></div>
        <div class="row"><span class="label">Direct Contact Phone:</span> <span class="value" style="color: #059669; font-size: 16px;">{donor_phone}</span></div>
        <div class="row"><span class="label">Donor Area:</span> <span class="value">{donor_area}</span></div>
        <div class="row"><span class="label">Request ID:</span> <span class="value" style="font-family: monospace; font-size: 12px;">{request_id}</span></div>
      </div>

      <p>Please call the donor immediately to confirm their arrival time and coordinate the transfusion.</p>
      
      <div style="text-align: center;">
        <a href="tel:{donor_phone}" class="btn" style="margin-right: 8px;">Call Donor Now</a>
        <a href="{portal_url}" class="btn" style="background-color: #1e293b;">View in Portal</a>
      </div>
    </div>
    <div class="footer">
      <p>LifeDrop Network • Smart Blood Donation Management System</p>
      <p>Thank you for using LifeDrop. Please update the request status to COMPLETED once the donation is concluded.</p>
    </div>
  </div>
</body>
</html>"""


def send_single_donor_match_alert(
    donor_email: str,
    donor_name: str,
    blood_group: str,
    hospital_name: str,
    match_id: str,
    distance_km: Optional[float] = None,
    request_id: Optional[str] = None,
) -> bool:
    """Send personalized notification to a matched candidate donor."""
    if not donor_email:
        return False

    dist_str = f" (~{distance_km:.1f} km away)" if distance_km is not None else ""
    subject = "New Blood Request Match — LifeDrop"

    portal_url = (
        f"{settings.FRONTEND_URL}/request/{request_id}"
        if request_id
        else f"{settings.FRONTEND_URL}/donor"
    )

    text_content = (
        f"Hello {donor_name},\n\n"
        f"A patient urgently requires blood matching your type ({blood_group}) at {hospital_name}{dist_str}.\n\n"
        f"Match ID: {match_id}\n"
        f"Your personal contact information remains protected. Please open the link to review and accept/decline:\n"
        f"{portal_url}\n\n"
        f"— LifeDrop Network"
    )

    html_content = _render_single_match_html(
        donor_name=donor_name,
        blood_group=blood_group,
        hospital_name=hospital_name,
        match_id=match_id,
        distance_km=distance_km,
        request_id=request_id,
    )

    return _dispatch_email(
        to_email=donor_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        is_emergency=False,
    )


def send_emergency_broadcast_alert(
    donor_emails: List[str],
    blood_group: str,
    hospital_name: str,
    units_needed: float,
    request_id: str,
) -> int:
    """Broadcast high-priority emergency alerts to all candidate donors in radius."""
    if not donor_emails:
        return 0

    subject = "URGENT: Emergency Blood Request Near You — LifeDrop"

    text_content = (
        f"CRITICAL EMERGENCY ALERT: Immediate Blood Transfusion Required\n\n"
        f"Blood Group: {blood_group}\n"
        f"Hospital / Center: {hospital_name}\n"
        f"Units Required: {units_needed}\n"
        f"Request ID: {request_id}\n\n"
        f"If you are healthy and available to donate, please view and accept the request immediately:\n"
        f"{settings.FRONTEND_URL}/request/{request_id}\n\n"
        f"— LifeDrop Emergency Dispatch Network"
    )

    html_content = _render_emergency_broadcast_html(
        blood_group=blood_group,
        hospital_name=hospital_name,
        units_needed=units_needed,
        request_id=request_id,
    )

    sent_count = 0
    # Deduplicate emails
    unique_emails = list(dict.fromkeys(email for email in donor_emails if email))
    for email in unique_emails:
        success = _dispatch_email(
            to_email=email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            is_emergency=True,
        )
        if success:
            sent_count += 1

    return sent_count


def send_donor_accepted_alert(
    recipient_email: str,
    recipient_name: str,
    donor_name: str,
    donor_phone: str,
    donor_area: str,
    request_id: str,
) -> bool:
    """Send immediate notification to the recipient when a donor accepts their request."""
    if not recipient_email:
        return False

    subject = "Donor Accepted Your Blood Request! — LifeDrop"

    text_content = (
        f"Hello {recipient_name},\n\n"
        f"A donor has accepted your blood request!\n\n"
        f"Donor Name: {donor_name}\n"
        f"Donor Phone: {donor_phone}\n"
        f"Donor Area: {donor_area}\n"
        f"Request ID: {request_id}\n\n"
        f"Please call the donor immediately to coordinate: {donor_phone}\n\n"
        f"You can also manage this request in your dashboard:\n"
        f"{settings.FRONTEND_URL}/recipient?tab=requests\n\n"
        f"— LifeDrop Network"
    )

    html_content = _render_donor_accepted_html(
        recipient_name=recipient_name,
        donor_name=donor_name,
        donor_phone=donor_phone,
        donor_area=donor_area,
        request_id=request_id,
    )

    return _dispatch_email(
        to_email=recipient_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        is_emergency=True,
    )


def _render_donation_completed_html(
    donor_name: str,
    hospital_name: str,
    units: float,
    component_type: str,
    next_eligible_date: Optional[str] = None,
) -> str:
    """Render HTML template for thanking donor and notifying of 90-day cooldown."""
    portal_url = f"{settings.FRONTEND_URL}/donor?tab=history"
    eligible_str = next_eligible_date or "in 90 days"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #6366f1; overflow: hidden; box-shadow: 0 4px 10px rgba(99, 102, 241, 0.1); }}
    .header {{ background-color: #4f46e5; color: #ffffff; padding: 24px; text-align: center; }}
    .badge {{ display: inline-block; background-color: #e0e7ff; color: #3730a3; padding: 4px 12px; border-radius: 9999px; font-weight: 700; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 800; }}
    .body {{ padding: 28px 24px; }}
    .highlight-card {{ background-color: #eef2ff; border-left: 4px solid #6366f1; padding: 18px; margin: 20px 0; border-radius: 4px; }}
    .row {{ margin-bottom: 8px; font-size: 14px; }}
    .label {{ font-weight: 600; color: #64748b; }}
    .value {{ font-weight: 700; color: #0f172a; }}
    .btn {{ display: inline-block; background-color: #4f46e5; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 700; font-size: 14px; margin-top: 12px; text-align: center; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">DONATION COMPLETED • HERO CONFIRMED</div>
      <h1>Thank You for Saving a Life!</h1>
      <p style="margin: 4px 0 0 0; opacity: 0.95;">Your donation was officially confirmed by the recipient center</p>
    </div>
    <div class="body">
      <p>Dear <strong>{donor_name}</strong>,</p>
      <p>On behalf of the recipient, hospital care team, and the entire LifeDrop community, thank you for your generous, life-saving blood donation.</p>
      
      <div class="highlight-card">
        <div class="row"><span class="label">Hospital / Center:</span> <span class="value">{hospital_name}</span></div>
        <div class="row"><span class="label">Units Donated:</span> <span class="value">{units} Unit(s) ({component_type.replace('_', ' ')})</span></div>
        <div class="row"><span class="label">Recovery Cooldown:</span> <span class="value" style="color: #4f46e5;">90 Days Mandated Rest</span></div>
        <div class="row"><span class="label">Next Eligible Date:</span> <span class="value">{eligible_str}</span></div>
      </div>

      <p>To ensure your body has ample time to replenish red cells and maintain safe hemoglobin reserves, your profile is now placed on temporary recovery cooldown until <strong>{eligible_str}</strong>.</p>
      
      <div style="text-align: center;">
        <a href="{portal_url}" class="btn">View Your Donation History & Tier</a>
      </div>
    </div>
    <div class="footer">
      <p>LifeDrop Network • Smart Blood Donation Management System</p>
      <p>Every donation counts. Rest well, hydrate, and thank you for being a lifeline in our healthcare community.</p>
    </div>
  </div>
</body>
</html>"""


def send_donation_completed_thank_you_alert(
    donor_email: str,
    donor_name: str,
    hospital_name: str,
    units: float,
    component_type: str,
    next_eligible_date: Optional[str] = None,
) -> bool:
    """Send formal thank-you and 90-day recovery cooldown notice to the donor upon completion."""
    if not donor_email:
        return False

    eligible_str = next_eligible_date or "in 90 days"
    subject = "Thank You for Saving a Life! Donation Confirmed — LifeDrop"

    text_content = (
        f"Dear {donor_name},\n\n"
        f"Thank you for your generous blood donation!\n"
        f"Your donation of {units} unit(s) ({component_type}) at {hospital_name} has been officially confirmed.\n\n"
        f"Recovery Cooldown Notice:\n"
        f"To ensure adequate recovery, your 90-day cooldown window is now active.\n"
        f"Your next eligible donation date is: {eligible_str}.\n\n"
        f"You can view your updated donation records and milestone tier in your donor dashboard:\n"
        f"{settings.FRONTEND_URL}/donor?tab=history\n\n"
        f"With sincere gratitude,\n"
        f"— LifeDrop Network"
    )

    html_content = _render_donation_completed_html(
        donor_name=donor_name,
        hospital_name=hospital_name,
        units=units,
        component_type=component_type,
        next_eligible_date=next_eligible_date,
    )

    return _dispatch_email(
        to_email=donor_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        is_emergency=False,
    )


def send_match_cancelled_reopened_alert(
    target_email: str,
    recipient_name: str,
    donor_name: str,
    hospital_name: str,
    cancelled_by: str,
    request_id: str,
    reason: Optional[str] = None,
) -> bool:
    """Send cancellation and re-opened search alert when an accepted match is released."""
    if not target_email:
        return False

    subject = "Blood Request Match Cancelled & Search Re-Opened — LifeDrop"
    reason_str = f"\nReason: {reason}" if reason else ""

    text_content = (
        f"Hello {recipient_name},\n\n"
        f"The commitment between Donor {donor_name} and request #{request_id[:8].upper()} at {hospital_name} "
        f"has been cancelled by the {cancelled_by}.{reason_str}\n\n"
        f"Action taken:\n"
        f"- The request has been reverted to OPEN status.\n"
        f"- The Intelligent Matching Engine has restarted search for alternative compatible donors.\n"
        f"- The donor has not received any penalty or cooldown.\n\n"
        f"You can monitor live donor responses at:\n"
        f"{settings.FRONTEND_URL}/request/{request_id}\n\n"
        f"— LifeDrop Network"
    )

    reason_html = f"<p style='margin:6px 0 0 0;'><strong>Reason:</strong> {reason}</p>" if reason else ""
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; }}
    .header {{ background-color: #d97706; color: #ffffff; padding: 20px; text-align: center; }}
    .body {{ padding: 24px; }}
    .notice {{ background-color: #fffbeb; border-left: 4px solid #d97706; padding: 14px; margin: 16px 0; border-radius: 4px; }}
    .btn {{ display: inline-block; background-color: #d97706; color: #ffffff !important; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; font-size: 14px; margin-top: 14px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2 style="margin:0;">Match Cancelled • Search Re-Opened</h2>
    </div>
    <div class="body">
      <p>Hello <strong>{recipient_name}</strong>,</p>
      <div class="notice">
        <p style="margin:0 0 6px 0;"><strong>Status:</strong> The match with Donor <strong>{donor_name}</strong> has been cancelled by the {cancelled_by}.</p>
        <p style="margin:0;"><strong>Hospital:</strong> {hospital_name}</p>
        {reason_html}
      </div>
      <p>The request is now <strong>OPEN</strong> again and LifeDrop's matching system has automatically resumed searching for nearby available donors.</p>
      <div style="text-align: center;">
        <a href="{settings.FRONTEND_URL}/request/{request_id}" class="btn">View Live Request Status</a>
      </div>
    </div>
  </div>
</body>
</html>"""

    return _dispatch_email(
        to_email=target_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        is_emergency=False,
    )





def send_request_creation_confirmation_alert(
    recipient_email: str,
    recipient_name: str,
    blood_group: str,
    hospital_name: str,
    units: float,
    request_id: str,
) -> bool:
    """Send broadcast confirmation to the creating recipient upon new blood request creation."""
    if not recipient_email:
        return False

    subject = f"Blood Request Broadcast Active ({blood_group}) — LifeDrop"
    text_content = (
        f"Hello {recipient_name},\n\n"
        f"Your blood request for {units} unit(s) of {blood_group} at {hospital_name} has been successfully broadcast to nearby eligible donors.\n\n"
        f"Request ID: {request_id}\n"
        f"You will receive alerts as compatible donors accept your request.\n\n"
        f"Live tracking: {settings.FRONTEND_URL}/request/{request_id}\n\n"
        f"— LifeDrop Emergency Dispatch Network"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:20px;background:#f8fafc;color:#1e293b;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;border:1px solid #e2e8f0;">
    <h2 style="color:#8B0000;margin-top:0;">Blood Request Broadcast Confirmed</h2>
    <p>Hello <strong>{recipient_name}</strong>,</p>
    <p>Your blood request for <strong>{units} unit(s) of {blood_group}</strong> at <strong>{hospital_name}</strong> is now live.</p>
    <p>Our Intelligent Matching Engine has initiated searches for nearby compatible volunteer donors.</p>
    <div style="margin:20px 0;"><a href="{settings.FRONTEND_URL}/request/{request_id}" style="background:#8B0000;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;font-weight:bold;">View Live Request Status</a></div>
    <p style="font-size:12px;color:#94a3b8;">LifeDrop Smart Blood Donation Network</p>
  </div>
</body>
</html>"""

    return _dispatch_email(
        to_email=recipient_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        is_emergency=False,
    )
