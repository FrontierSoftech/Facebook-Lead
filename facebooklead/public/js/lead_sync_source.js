frappe.ui.form.on("Lead Sync Source", {
  refresh(frm) {
    if (frm.doc.type !== "Facebook" || frm.is_new()) return;
    frm.add_custom_button(__("Refresh FB Forms"), () => {
      frappe.call({
        method: "facebooklead.fb_refresh.refresh_facebook_forms",
        args: { source_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Fetching latest forms from Facebook..."),
        callback: () => {
          frappe.show_alert({ message: __("Forms refreshed"), indicator: "green" });
          frm.refresh_field("facebook_lead_form");
        },
      });
    });
  },
});