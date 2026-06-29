import frappe
from crm.lead_syncing.doctype.lead_sync_source.facebook import (
    fetch_and_store_pages_from_facebook,
)

@frappe.whitelist()
def refresh_facebook_forms(source_name: str):
    source = frappe.get_doc("Lead Sync Source", source_name)
    if source.type != "Facebook" or not source.access_token:
        frappe.throw("Not a Facebook source or token missing")
    
    fetch_and_store_pages_from_facebook(source.get_password("access_token"))
    return {"ok": True}