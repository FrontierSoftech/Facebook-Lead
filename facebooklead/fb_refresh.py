import frappe
import requests
from crm.lead_syncing.doctype.lead_sync_source.facebook import (
    fetch_and_store_pages_from_facebook,
    fetch_and_store_leadgen_forms_from_facebook,
)


def _handle_fb_error(e):
    """Extract FB's real error message from HTTPError."""
    try:
        fb_error = e.response.json().get("error", {}).get("message", str(e))
    except Exception:
        fb_error = str(e)
    frappe.throw(f"Facebook API error: {fb_error}")


def _refresh_selected_page(source):
    """Refresh forms only for the page selected on the source."""
    page_doc = frappe.get_doc("Facebook Page", source.facebook_page)
    page_token = page_doc.get_password("access_token")
    fetch_and_store_leadgen_forms_from_facebook(source.facebook_page, page_token)


def _refresh_all_pages(source):
    """Refresh pages + forms across the whole token (also picks up new pages)."""
    fetch_and_store_pages_from_facebook(source.get_password("access_token"))


@frappe.whitelist()
def refresh_facebook_forms(source_name: str):
    """Manual refresh — called from the button. Scoped to selected page if set."""
    source = frappe.get_doc("Lead Sync Source", source_name)
    if source.type != "Facebook" or not source.access_token:
        frappe.throw("Not a Facebook source or token missing")

    try:
        if source.facebook_page:
            _refresh_selected_page(source)
        else:
            _refresh_all_pages(source)
    except requests.exceptions.HTTPError as e:
        _handle_fb_error(e)

    return {"ok": True}


def refresh_all_facebook_forms():
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
            if source.facebook_page:
                _refresh_selected_page(source)
            else:
                _refresh_all_pages(source)
        except Exception:
            frappe.log_error(
                title=f"FB form refresh failed for {name}",
                message=frappe.get_traceback(),
            )