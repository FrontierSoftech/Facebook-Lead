import frappe
import requests
import json
import hmac
import hashlib

GRAPH_VERSION = "v25.0"
PAGE_ID = "643095628889549"


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def fb_lead_webhook():
    if frappe.request.method == "GET":
        mode = frappe.form_dict.get("hub.mode")
        token = frappe.form_dict.get("hub.verify_token")
        challenge = frappe.form_dict.get("hub.challenge")
        if mode == "subscribe" and token == frappe.conf.get("fb_verify_token"):
            frappe.response["type"] = "plain"
            return int(challenge)
        frappe.throw("Verification failed", frappe.AuthenticationError)

    verify_signature()
    data = json.loads(frappe.request.get_data())

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change["value"]
            frappe.enqueue(
                "customization_sendil.api.fb_leads.process_lead",
                queue="short",
                leadgen_id=value["leadgen_id"],
                form_id=value.get("form_id"),
                ad_id=value.get("ad_id"),
                page_id=value.get("page_id"),
                campaign_id=value.get("campaign_id"),
            )
    return "ok"


def verify_signature():
    sig = frappe.get_request_header("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        frappe.throw("Missing signature", frappe.AuthenticationError)
    expected = hmac.new(
        frappe.conf.get("fb_app_secret").encode(),
        frappe.request.get_data(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig.split("=")[1], expected):
        frappe.throw("Invalid signature", frappe.AuthenticationError)


def process_lead(leadgen_id, form_id=None, ad_id=None, page_id=None, campaign_id=None):
    token = frappe.conf.get("fb_page_token")
    # if frappe.db.exists("Lead", {"custom_fb_leadgen_id": leadgen_id}):
    #     return 
    # Fetch lead details
    lead_res = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{leadgen_id}",
        params={"access_token": token},
        timeout=10,
    )
    lead_res.raise_for_status()
    lead = lead_res.json()

    # Convert field_data array → dict
    fields = {f["name"]: f["values"][0] for f in lead.get("field_data", []) if f.get("values")}

    # Fetch form name (cached per form_id to avoid hammering API)
    form_name = get_form_name(form_id, token) if form_id else "Unknown Form"

    # Build readable notes from all fields
    notes_lines = [f"📋 Form: {form_name}", f"🆔 Form ID: {form_id}", f"📢 Ad ID: {ad_id}", ""]
    for key, val in fields.items():
        label = key.replace("_", " ").title()
        notes_lines.append(f"{label}: {val}")
    notes = "\n".join(notes_lines)

    # Create Lead doc
    doc = frappe.get_doc({
        "doctype": "Lead",
        "lead_name": (
            fields.get("full_name")
            or fields.get("name")
            or fields.get("first_name", "") + " " + fields.get("last_name", "")
        ).strip() or "Facebook Lead",
        "email_id": fields.get("email"),
        "mobile_no": fields.get("phone_number") or fields.get("phone"),
        "company_name": fields.get("company_name") or fields.get("company"),
        "website": fields.get("website"),
        "city": fields.get("city"),
        "source": "Facebook",
        "notes": notes,
        # Optional custom fields — add them to Lead DocType if you want
        # "custom_fb_form_id": form_id,
        # "custom_fb_form_name": form_name,
        # "custom_fb_ad_id": ad_id,
        # "custom_fb_campaign_id": campaign_id,
        # "custom_fb_leadgen_id": leadgen_id,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()


def get_form_name(form_id, token):
    """Cache form names to avoid extra API calls."""
    cache_key = f"fb_form_name:{form_id}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        res = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{form_id}",
            params={"fields": "name", "access_token": token},
            timeout=5,
        )
        name = res.json().get("name", "Unknown")
        frappe.cache().set_value(cache_key, name, expires_in_sec=86400)  # 24h cache
        return name
    except Exception:
        return "Unknown"


def keepalive_token():
    """Weekly ping to keep Data Access timer fresh."""
    token = frappe.conf.get("fb_page_token")
    try:
        r = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{PAGE_ID}",
            params={"fields": "name", "access_token": token},
            timeout=10,
        )
        if r.status_code != 200:
            frappe.log_error(r.text, "FB Token Keepalive Failed")
    except Exception as e:
        frappe.log_error(str(e), "FB Token Keepalive Error")