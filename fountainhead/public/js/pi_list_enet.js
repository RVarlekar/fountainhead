// Purchase Invoice list: generate the HDFC E-Net vendor-payment file from the
// selected (submitted, unpaid) invoices — replacing the Tally-extract → VLOOKUP
// → RBI-sheet routine. The file only gets built; uploading it to E-Net and the
// bank's own approvals stay exactly where they are today.
frappe.listview_settings["Purchase Invoice"] = frappe.listview_settings["Purchase Invoice"] || {};

(function () {
	const settings = frappe.listview_settings["Purchase Invoice"];
	const prev_onload = settings.onload;

	settings.onload = function (listview) {
		if (prev_onload) prev_onload(listview);

		listview.page.add_action_item(__("🏦 E-Net payment file"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select the invoices to pay first."));
				return;
			}
			frappe.call({
				method: "fountainhead.bill_ocr.payments.make_enet_file",
				args: { invoice_names: names },
				freeze: true,
				freeze_message: __("Writing the payment file…"),
				callback: (r) => {
					const m = r.message;
					if (!m) return;
					// Hand the file to the browser — nothing is stored server-side.
					const blob = new Blob([m.content], { type: "text/plain" });
					const a = document.createElement("a");
					a.href = URL.createObjectURL(blob);
					a.download = m.filename;
					a.click();
					URL.revokeObjectURL(a.href);
					let msg = __("{0}: {1} payment(s) totalling {2}.", [
						m.filename,
						m.rows,
						format_currency(m.total, frappe.defaults.get_default("currency")),
					]);
					if ((m.skipped || []).length) {
						msg += "<br><b>" + __("Skipped") + ":</b><br>" + m.skipped.join("<br>");
					}
					frappe.msgprint({ title: __("E-Net file ready"), message: msg, indicator: (m.skipped || []).length ? "orange" : "green" });
				},
			});
		});
	};
})();
