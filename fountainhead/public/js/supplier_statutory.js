// Supplier: GSTIN → PAN, instantly, in the browser (the server hook re-validates).
// Rule from accounts (1 Sept): GSTIN is 15 characters; characters 3–12 ARE the
// PAN — 24AADFF3677P1ZY → AADFF3677P. Nobody should ever type a PAN when the
// GSTIN is known.
frappe.ui.form.on("Supplier", {
	custom_gstin(frm) {
		const gstin = (frm.doc.custom_gstin || "").trim().toUpperCase();
		if (!gstin) return;
		if (gstin !== frm.doc.custom_gstin) frm.set_value("custom_gstin", gstin);
		if (gstin.length !== 15) {
			frappe.show_alert({
				message: __("A GSTIN has 15 characters — this one has {0}.", [gstin.length]),
				indicator: "orange",
			});
			return;
		}
		const pan = gstin.substring(2, 12);
		if (frm.doc.custom_pan !== pan) {
			frm.set_value("custom_pan", pan);
			frappe.show_alert({
				message: __("PAN filled from the GSTIN: {0}", [pan]),
				indicator: "green",
			});
		}
	},
});
