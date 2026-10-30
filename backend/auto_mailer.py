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
    founders_count = len([r for r in records if r.get("founder_name") and r.get("founder_name") != "Not Found"])
    websites_count = len([r for r in records if r.get("website") and r.get("website") != "Not Found"])

    now_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    rows_html = ""
    for idx, r in enumerate(records[:50], 1):  # Display top 50 in email body; full in attached CSV/Excel
        b_name = r.get("brand_name", "Unknown")
        asin = r.get("asin", "")
        p_url = r.get("product_url", f"https://www.amazon.com/dp/{asin}")
        reviews = r.get("reviews", 0)
        cat_max = r.get("catalog_max_reviews", reviews)
        country = r.get("seller_country_display") or r.get("seller_country") or "Unknown"
        legal_name = r.get("seller_business_name", "-")
        seller_ph = r.get("seller_phone", "Not Found")
        seller_em = r.get("seller_email", "Not Found")
        web = r.get("website", "Not Found")
        outreach_em = r.get("email", "Not Found")
        outreach_ph = r.get("phone", "Not Found")
        founder = r.get("founder_name", "Not Found")
        linkedin = r.get("linkedin_url", "Not Found")

        linkedin_link = f'<a href="{linkedin}" style="color:#0a66c2;text-decoration:none;font-weight:600;" target="_blank">LinkedIn Profile</a>' if linkedin != "Not Found" else '<span style="color:#94a3b8">Not Found</span>'
        website_link = f'<a href="{web}" style="color:#0284c7;text-decoration:none;font-weight:600;" target="_blank">Visit Site</a>' if web != "Not Found" else '<span style="color:#94a3b8">Not Found</span>'
        email_str = f'<a href="mailto:{outreach_em}" style="color:#f59e0b;text-decoration:none;font-weight:600;">{outreach_em}</a>' if outreach_em != "Not Found" else '<span style="color:#94a3b8">-</span>'
        phone_str = f'<span style="color:#8b5cf6;font-weight:600;">{outreach_ph}</span>' if outreach_ph != "Not Found" else '<span style="color:#94a3b8">-</span>'

        # Show seller info specifics if extracted
        seller_details = f"<b>{legal_name}</b> ({country})"
        if seller_ph != "Not Found" or seller_em != "Not Found":
            seller_details += f"<br><small style='color:#64748b;'>Amazon CS: {seller_ph if seller_ph != 'Not Found' else ''} {seller_em if seller_em != 'Not Found' else ''}</small>"

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; font-size: 13px;">
            <td style="padding: 10px 8px;"><b>{idx}</b></td>
            <td style="padding: 10px 8px;">
                <b style="color: #0f172a; font-size: 14px;">{b_name}</b><br>
                <a href="{p_url}" style="color: #0284c7; text-decoration: none; font-size: 11px;" target="_blank">ASIN: {asin}</a>
            </td>
            <td style="padding: 10px 8px;">
                <span style="background: #ecfdf5; color: #047857; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 11px;">
                    🔥 {reviews} revs (Max: {cat_max})
                </span><br>
                <span style="color: #10b981; font-size: 10px; font-weight: 600;">🛡️ All SKUs &lt; 100</span>
            </td>
            <td style="padding: 10px 8px;">{seller_details}</td>
            <td style="padding: 10px 8px;">
                {website_link}<br>
                ✉️ {email_str}<br>
                📞 {phone_str}
            </td>
            <td style="padding: 10px 8px;">
                <b>{founder}</b><br>
                {linkedin_link}
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 900px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 25px 30px; color: #ffffff; }}
            .header h1 {{ margin: 0 0 6px 0; font-size: 22px; color: #f8fafc; font-weight: 700; }}
            .header p {{ margin: 0; font-size: 13px; color: #94a3b8; }}
            .stats-bar {{ display: flex; background: #f1f5f9; padding: 15px 25px; border-bottom: 1px solid #e2e8f0; }}
            .stat-box {{ flex: 1; text-align: center; border-right: 1px solid #cbd5e1; }}
            .stat-box:last-child {{ border-right: none; }}
            .stat-val {{ font-size: 20px; font-weight: 800; color: #0f172a; }}
            .stat-lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; font-weight: 600; margin-top: 2px; }}
            .content {{ padding: 25px; }}
            .table-wrap {{ overflow-x: auto; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th {{ background: #f8fafc; padding: 10px 8px; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: 0.5px; border-bottom: 2px solid #cbd5e1; }}
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
                    <div class="stat-val" style="color:#10b981;">100%</div>
                    <div class="stat-lbl">All SKUs &lt; 100 Revs</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#f59e0b;">{emails_count}</div>
                    <div class="stat-lbl">Emails Found</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#8b5cf6;">{phones_count}</div>
                    <div class="stat-lbl">Phones Found</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val" style="color:#0a66c2;">{founders_count}</div>
                    <div class="stat-lbl">Founders Identified</div>
                </div>
            </div>
            <div class="content">
                <p style="font-size: 14px; margin-top: 0; color: #334155;">
                    Here are your latest verified Private Label leads. Every brand below has been verified with <b>all catalog products under 100 reviews</b> and non-China registered sellers. Complete records are attached in <b>CSV and Excel</b> format.
                </p>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Brand & ASIN</th>
                                <th>Reviews Audit</th>
                                <th>Seller & Origin</th>
                                <th>Website & Contacts</th>
                                <th>Decision Maker</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="footer">
                Attached: <b>leads.csv</b> and <b>leads.xlsx</b> with complete legal entity addresses, Amazon seller phone/email, brand website, decision maker profiles.
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_leads_email(
    records: List[Dict[str, Any]],
    subject: Optional[str] = None,
    receiver_email: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Dispatches automated lead email with formatted HTML body and CSV/Excel attachments.
    """
    if not records:
        return False, "No records provided to send."

    cfg = config or get_email_config()
    sender = cfg.get("sender_email", "").strip()
    pwd = cfg.get("sender_password", "").strip()
    receiver = (receiver_email or cfg.get("receiver_email", "")).strip()
    smtp_host = cfg.get("smtp_host", "smtp.gmail.com").strip()
    smtp_port = cfg.get("smtp_port", 465)
    use_ssl = cfg.get("use_ssl", True)

    if not sender or not pwd:
        return False, "Missing sender email or password/app-password. Configure SENDER_EMAIL and SENDER_PASSWORD."
    if not receiver:
        return False, "Missing receiver email. Configure RECEIVER_EMAIL."

    date_tag = datetime.now().strftime("%Y-%m-%d")
    email_subject = subject or f"🎯 Amazon PL Hunter: {len(records)} New Verified Leads ({date_tag})"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = email_subject
    msg["From"] = sender
    msg["To"] = receiver

    # HTML Body
    html_content = build_leads_html(records, title=f"{len(records)} New Verified Private Label Leads")
    msg.attach(MIMEText(html_content, "html"))

    # Attachment 1: CSV
    try:
        csv_bytes = export_to_csv_bytes(records)
        part_csv = MIMEBase("text", "csv")
        part_csv.set_payload(csv_bytes)
        encoders.encode_base64(part_csv)
        part_csv.add_header("Content-Disposition", f'attachment; filename="pl_leads_{date_tag}.csv"')
        msg.attach(part_csv)
    except Exception as e:
        print(f"Warning attaching CSV: {e}")

    # Attachment 2: Excel
    try:
        excel_bytes = export_to_excel_bytes(records)
        part_xlsx = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        part_xlsx.set_payload(excel_bytes)
        encoders.encode_base64(part_xlsx)
        part_xlsx.add_header("Content-Disposition", f'attachment; filename="pl_leads_{date_tag}.xlsx"')
        msg.attach(part_xlsx)
    except Exception as e:
        print(f"Warning attaching Excel: {e}")

    # Send via SMTP
    try:
        if use_ssl and smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(sender, pwd)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.starttls()
                server.login(sender, pwd)
                server.send_message(msg)

        return True, f"Successfully dispatched email with {len(records)} leads to {receiver}."
    except Exception as e:
        return False, f"SMTP Error sending email: {str(e)}"
