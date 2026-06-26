import frappe
import requests
import json
import hmac
import hashlib
from werkzeug.wrappers import Response

GRAPH_VERSION = "v25.0"


def get_settings():
    """Fetch Facebook credentials from settings doctype."""
    settings = frappe.get_single("Facebook Lead Settings")
    return {
        "app_secret": settings.get_password("fb_app_secret"),
        "page_token": settings.get_password("fb_page_token"),
        "verify_token": settings.fb_verify_token,
        "page_id": settings.fb_page_id,
    }


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def fb_lead_webhook():
    cfg = get_settings()

    if frappe.request.method == "GET":
        mode = frappe.form_dict.get("hub.mode")
        token = frappe.form_dict.get("hub.verify_token")
        challenge = frappe.form_dict.get("hub.challenge")
        if mode == "subscribe" and token == cfg["verify_token"]:
            return Response(challenge, mimetype='text/plain')
        frappe.throw("Verification failed", frappe.AuthenticationError)

    verify_signature(cfg["app_secret"])
    data = json.loads(frappe.request.get_data())

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change["value"]
            frappe.enqueue(
                "facebooklead.fb_leads.process_lead",
                queue="short",
                leadgen_id=value["leadgen_id"],
                form_id=value.get("form_id"),
                ad_id=value.get("ad_id"),
            )
    return "ok"


def verify_signature(app_secret):
    sig = frappe.get_request_header("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        frappe.throw("Missing signature", frappe.AuthenticationError)
    expected = hmac.new(
        app_secret.encode(),
        frappe.request.get_data(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig.split("=")[1], expected):
        frappe.throw("Invalid signature", frappe.AuthenticationError)


def process_lead(leadgen_id, form_id=None, ad_id=None):
    if frappe.db.exists("CRM Lead", {"facebook_lead_id": leadgen_id}):
        return

    cfg = get_settings()
    token = cfg["page_token"]

    res = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{leadgen_id}",
        params={"access_token": token},
        timeout=10,
    )
    res.raise_for_status()
    lead = res.json()

    fields = {f["name"]: f["values"][0] for f in lead.get("field_data", []) if f.get("values")}

    full_name = (fields.get("full_name") or fields.get("name") or "Facebook Lead").strip()
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    doc = frappe.get_doc({
        "doctype": "CRM Lead",
        "first_name": first_name,
        "last_name": last_name,
        "email": fields.get("email"),
        "mobile_no": fields.get("phone_number") or fields.get("phone"),
        "phone": fields.get("phone_number") or fields.get("phone"),
        "organization": fields.get("company_name"),
        "website": fields.get("website"),
        "job_title": fields.get("job_title"),
        "source": "Facebook",
        "status": "New",
        "lead_owner": "Administrator",
        "facebook_lead_id": leadgen_id,
        "facebook_form_id": form_id,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()


def keepalive_token():
    cfg = get_settings()
    if not cfg["page_id"] or not cfg["page_token"]:
        return
    try:
        r = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{cfg['page_id']}",
            params={"fields": "name", "access_token": cfg["page_token"]},
            timeout=10,
        )
        if r.status_code != 200:
            frappe.log_error(r.text, "FB Token Keepalive Failed")
    except Exception as e:
        frappe.log_error(str(e), "FB Token Keepalive Error")