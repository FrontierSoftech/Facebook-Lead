import frappe
from crm.lead_syncing.doctype.lead_sync_source.facebook import (
    fetch_and_store_pages_from_facebook,
)


@frappe.whitelist()
def refresh_facebook_forms(source_name: str):
    """Manual refresh — called from the button."""
    source = frappe.get_doc("Lead Sync Source", source_name)
    if source.type != "Facebook" or not source.access_token:
        frappe.throw("Not a Facebook source or token missing")
    
    fetch_and_store_pages_from_facebook(source.get_password("access_token"))
    return {"ok": True}


def refresh_all_facebook_forms_daily():
    """Scheduler — runs for every enabled Facebook source."""
    sources = frappe.get_all(
        "Lead Sync Source",
        filters={"enabled": 1, "type": "Facebook"},
        pluck="name",
    )
    for name in sources:
        try:
            source = frappe.get_doc("Lead Sync Source", name)
            if not source.access_token:
                continue
            fetch_and_store_pages_from_facebook(source.get_password("access_token"))
        except Exception:
            frappe.log_error(
                title=f"FB form refresh failed for {name}",
                message=frappe.get_traceback(),
            )
