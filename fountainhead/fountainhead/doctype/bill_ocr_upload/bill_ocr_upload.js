// One queued bill. Read it here; create the Purchase Receipt from it.
//
// "Create Purchase Receipt" opens the normal new-document form with the bill
// already attached — the standard Bill OCR flow then fills the form from the
// READING STORED ON THIS ROW (no second paid API call), and the person reviews
// and saves exactly as they would for a single bill. This queue never creates
// or submits documents by itself.

frappe.ui.form.on("Bill OCR Upload", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status !== "Read") {
			frm.page.set_primary_action(
				frm.doc.status === "Error" ? __("Retry reading") : __("Read this bill"),
				() => {
					frappe.call({
						method: "fountainhead.bill_ocr.api.read_upload",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Reading the bill…"),
						callback: () => frm.reload_doc(),
					});
				}
			);
		}

		if (frm.doc.status === "Read") {
			const target = frm.doc.target_doctype || "Purchase Receipt";
			frm.page.set_primary_action(__("Create {0}", [__(target)]), () => {
				// The new form's custom_attachment trigger picks this up on load and
				// fills the form from the reading cached on this row.
				frappe.route_options = { custom_attachment: frm.doc.bill_file };
				frappe.new_doc(target);
			});
		}
	},
});
