import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

def get_email_config() -> Dict[str, Any]:
    """
    Loads email configuration from environment variables or email_config.json.
    """
    config = {
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "465")),
        "use_ssl": os.getenv("SMTP_USE_SSL", "true").lower() in ["true", "1", "yes"],
        "sender_email": os.getenv("SENDER_EMAIL", ""),
        "sender_password": os.getenv("SENDER_PASSWORD", ""),
        "receiver_email": os.getenv("RECEIVER_EMAIL", "")
    }

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "email_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for k, v in saved.items():
                    if v and not config.get(k):
                        config[k] = v
        except Exception:
            pass

    return config

def build_leads_html(records: List[Dict[str, Any]], title: str = "Amazon Private Label Leads Report") -> str:
    """Builds a responsive, professional HTML summary email for the leads."""
    total = len(records)
    emails_count = len([r for r in records if r.get("email") and r.get("email") != "Not Found"])
    phones_count = len([r for r in records if r.get("phone") and r.get("phone") != "Not Found"])
    direct_contacts_count = len([r for r in records if "Direct Decision Maker" in str(r.get("contact_quality", ""))])
    new_launches_count = len([r for r in records if "New Launch" in str(r.get("brand_persona", ""))])
    distressed_count = len([r for r in records if "Distressed" in str(r.get("brand_persona", "")) or r.get("has_frequently_returned_badge")])

    now_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    cards_html = ""
    for idx, r in enumerate(records[:50], 1):  # Display top 50 in email body; full in attached CSV/Excel
        b_name = r.get("brand_name", "Unknown")
        asin = r.get("asin", "")
        p_url = r.get("product_url", f"https://www.amazon.com/dp/{asin}")
        reviews = r.get("reviews", 0)
        cat_max = r.get("catalog_max_reviews", reviews)
        rating = r.get("rating", "")
        country = r.get("seller_country_display") or r.get("seller_country") or "Unknown"
        legal_name = r.get("seller_business_name", "-")
        web = r.get("website", "Not Found")
        outreach_em = r.get("email", "Not Found")
        email_type = r.get("email_type", "None")
        outreach_ph = r.get("phone", "Not Found")
        founder = r.get("founder_name", "Not Found")
        linkedin = r.get("linkedin_url", "Not Found")
        persona = r.get("brand_persona", "🌱 Growing Challenger")
        contact_qual = r.get("contact_quality", "📧 General / Support Only")
        launch_date = r.get("date_first_available", "Not Listed")
        pitch_hook = r.get("growth_pitch_hook", "")
        health_summary = r.get("catalog_health_summary", "")

        # Persona Badge colors
        if "New Launch" in persona:
            persona_badge_html = '<span style="background:#dcfce7;color:#15803d;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">🚀 New Launch Brand</span>'
        elif "Stagnant Veteran" in persona:
            persona_badge_html = '<span style="background:#fef3c7;color:#b45309;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">📉 Stagnant Veteran (2+ Yrs)</span>'
        elif "Distressed" in persona:
            persona_badge_html = '<span style="background:#fee2e2;color:#b91c1c;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">⚠️ Distressed Catalog</span>'
        else:
            persona_badge_html = '<span style="background:#e0f2fe;color:#0369a1;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">🌱 Growing Challenger</span>'

        # Contact Quality Badge
        if "Direct Decision Maker" in contact_qual:
            qual_badge_html = '<span style="background:#f3e8ff;color:#7e22ce;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">⭐ Direct Founder Contact</span>'
        elif "General" in contact_qual:
            qual_badge_html = '<span style="background:#f1f5f9;color:#475569;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:600;">📧 General / Support</span>'
        else:
            qual_badge_html = '<span style="background:#fef2f2;color:#991b1b;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:600;">❌ Uncontactable</span>'

        # Problem alerts
        alert_pills = []
        if r.get("has_frequently_returned_badge"):
            alert_pills.append('<span style="background:#ffedd5;color:#c2410c;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">🔥 Frequently Returned Badge</span>')
        if r.get("is_buybox_suppressed"):
            alert_pills.append('<span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">🛑 Buy Box Suppressed</span>')
        if r.get("is_suppressed"):
            alert_pills.append('<span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">📦 Listing Unavailable</span>')
        alerts_html = " ".join(alert_pills) if alert_pills else ""

        linkedin_link = f'<a href="{linkedin}" style="color:#0a66c2;text-decoration:none;font-weight:600;" target="_blank">LinkedIn Profile</a>' if linkedin != "Not Found" else '<span style="color:#94a3b8">Not Found</span>'
        website_link = f'<a href="{web}" style="color:#0284c7;text-decoration:none;font-weight:600;" target="_blank">Visit Site</a>' if web != "Not Found" else '<span style="color:#94a3b8">Not Found</span>'
        
        email_tag = f" ({email_type})" if email_type != "None" else ""
        email_str = f'<a href="mailto:{outreach_em}" style="color:#0284c7;text-decoration:none;font-weight:700;">{outreach_em}</a>{email_tag}' if outreach_em != "Not Found" else '<span style="color:#94a3b8">-</span>'
        phone_str = f'<span style="color:#7e22ce;font-weight:600;">{outreach_ph}</span>' if outreach_ph != "Not Found" else '<span style="color:#94a3b8">-</span>'

        cards_html += f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:16px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #f1f5f9; padding-bottom:8px;">
                <div>
                    <span style="font-weight:800; font-size:16px; color:#0f172a;">#{idx}. {b_name}</span>
                    <span style="margin-left:8px;">{persona_badge_html}</span>
                    <span style="margin-left:6px;">{qual_badge_html}</span>
                </div>
                <div style="font-size:12px; color:#64748b;">
                    Launched: <b>{launch_date}</b>
                </div>
            </div>

            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; font-size:12px; margin-bottom:10px;">
                <div>
                    <b>Amazon Listing:</b> <a href="{p_url}" target="_blank" style="color:#0284c7;text-decoration:none;font-weight:600;">ASIN: {asin}</a> &bull; {reviews} revs (Max: {cat_max}) {f'&bull; {rating}★' if rating else ''}<br>
                    <b>Seller Legal Entity:</b> {legal_name} ({country})<br>
                    {f'<b>Listing Alerts:</b> {alerts_html}<br>' if alerts_html else ''}
                </div>
                <div>
                    <b>Decision Maker:</b> {founder} &bull; {linkedin_link}<br>
                    <b>Outreach Contact:</b> {email_str} &bull; {phone_str}<br>
                    <b>Brand Website:</b> {website_link}
                </div>
            </div>

            {f'''
            <div style="background:#f8fafc; border-left:3px solid #3b82f6; padding:8px 12px; border-radius:4px; font-size:12px; color:#334155; line-height:1.4;">
                <b style="color:#1e40af;">🎯 Outreach Pitch Hook:</b><br>
                "{pitch_hook}"
            </div>
            ''' if pitch_hook else ''}
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 900px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 25px 30px; color: #ffffff; }}
            .header h1 {{ margin: 0 0 6px 0; font-size: 22px; color: #f8fafc; font-weight: 700; }}
            .header p {{ margin: 0; font-size: 13px; color: #94a3b8; }}
            .stats-bar {{ display: flex; background: #f1f5f9; padding: 15px 25px; border-bottom: 1px solid #e2e8f0; }}
            .stat-box {{ flex: 1; text-align: center; border-right: 1px solid #cbd5e1; }}
            .stat-box:last-child {{ border-right: none; }}
            .stat-val {{ font-size: 20px; font-weight: 800; color: #0f172a; }}
            .stat-lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; font-weight: 600; margin-top: 2px; }}
            .content {{ padding: 25px; background: #f8fafc; }}
            .footer {{ background: #f8fafc; padding: 15px 25px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎯 {title}</h1>
                <p>Automated Private Label Lead Hunter &bull; {now_str}</p>
            </div>
            <div class="stats-bar">
                <div class="stat-box">
                    <div class="stat-val" style="color:#0284c7;">{total}</div>
                    <div class="stat-lbl">PL Brands Found</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#7e22ce;">{direct_contacts_count}</div>
                    <div class="stat-lbl">Direct Founders</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#15803d;">{new_launches_count}</div>
                    <div class="stat-lbl">New Launches</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#b91c1c;">{distressed_count}</div>
                    <div class="stat-lbl">Distressed / Turnarounds</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#10b981;">{emails_count}</div>
                    <div class="stat-lbl">Reachable Leads</div>
                </div>
            </div>
            <div class="content">
                <p style="font-size: 14px; margin-top: 0; margin-bottom: 16px; color: #334155;">
                    Here are your latest verified Private Label leads with <b>all catalog products under 100 reviews</b>, listing health problem audits, and tailored cold pitch hooks. Complete records are attached in <b>CSV and Excel</b>.
                </p>
                {cards_html}
            </div>
            <div class="footer">
                Attached: <b>leads.csv</b> and <b>leads.xlsx</b> with complete Brand Persona segmentation, Listing Health flags, and Direct Decision Maker contacts.
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_leads_email(
    records: List[Dict[str, Any]],
    subject: Optional[str] = None,
    custom_config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Sends an automated email containing lead summary cards and attached CSV/Excel.
    """
    if not records:
        return False, "No records to email."

    cfg = custom_config or get_email_config()
    sender = cfg.get("sender_email")
    pwd = cfg.get("sender_password")
    receiver = cfg.get("receiver_email")
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 465))
    use_ssl = cfg.get("use_ssl", True)

    if not sender or not pwd or not receiver:
        return False, "Missing SMTP credentials. Please configure your sender email, app password, and receiver email."

    email_subject = subject or f"🎯 {len(records)} New Private Label Leads ({datetime.now().strftime('%b %d, %Y')})"

    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = f"Amazon PL Hunter <{sender}>"
        msg["To"] = receiver
        msg["Subject"] = email_subject

        # Email Body (HTML)
        html_content = build_leads_html(records, title=email_subject)
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # Attach CSV
        try:
            csv_data = export_to_csv_bytes(records)
            part_csv = MIMEBase("application", "octet-stream")
            part_csv.set_payload(csv_data)
            encoders.encode_base64(part_csv)
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            part_csv.add_header("Content-Disposition", f'attachment; filename="pl_leads_{timestamp_str}.csv"')
            msg.attach(part_csv)
        except Exception as e:
            print(f"Notice attaching CSV: {e}")

        # Attach Excel
        try:
            xlsx_data = export_to_excel_bytes(records)
            part_xlsx = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part_xlsx.set_payload(xlsx_data)
            encoders.encode_base64(part_xlsx)
            part_xlsx.add_header("Content-Disposition", f'attachment; filename="pl_leads_{timestamp_str}.xlsx"')
            msg.attach(part_xlsx)
        except Exception as e:
            print(f"Notice attaching Excel: {e}")

        # Dispatch via SMTP
        if use_ssl or port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()

        server.login(sender, pwd)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()

        return True, f"Successfully sent leads report with {len(records)} brands to {receiver}."
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"
