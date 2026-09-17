// Purchase Invoice: the "Suggest TDS" button — shows the full working (section,
// rate, cumulative, threshold, reason) and applies the deduction row ONLY when
// the maker clicks Apply. The engine computes; the human decides. Rules live in
// the Bill TDS Rule doctype (accounts-editable), never in this file.
frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.supplier) return;
		frm.add_custom_button(__("Suggest TDS"), () => {
			frappe.call({
				method: "fountainhead.bill_ocr.tds.compute_tds",
				args: {
					supplier: frm.doc.supplier,
					company: frm.doc.company,
					taxable_amount: frm.doc.base_net_total || frm.doc.net_total || frm.doc.grand_total || 0,
					bill_date: frm.doc.bill_date || frm.doc.posting_date,
					exclude_invoice: frm.doc.__islocal ? null : frm.doc.name,
				},
				freeze: true,
				callback: (r) => {
					const t = r.message;
					if (!t) return;
					if (!t.section) {
						frappe.msgprint(t.reason);
						return;
					}
					const row = (k, v) => `<tr><td>${k}</td><td class="text-right"><b>${v}</b></td></tr>`;
					const money = (v) => format_currency(v, frm.doc.currency);
					const html = `
						<table class="table table-bordered table-condensed">
							${row(__("Section"), `${t.section} <span class="text-muted">(${t.old_section || "—"})</span>`)}
							${row(__("Nature"), t.nature || "—")}
							${row(__("Vendor type"), t.vendor_type)}
							${row(__("PAN"), (t.pan || __("MISSING")) + (t.pan_ok ? "" : " ⚠"))}
							${row(__("Previous cumulative (FY {0})", [t.fy]), money(t.previous_cumulative))}
							${row(__("This bill (GST-exclusive)"), money(t.current_bill))}
							${row(__("Cumulative"), money(t.cumulative))}
							${row(__("Threshold (per bill / aggregate)"), `${t.threshold_single ? money(t.threshold_single) : "—"} / ${t.threshold_aggregate ? money(t.threshold_aggregate) : "—"}`)}
							${row(__("Rate"), t.rate + "%" + (t.rate_note || ""))}
							${row(__("TDS on"), money(t.tds_base))}
							${row(__("TDS amount"), money(t.tds_amount))}
							${row(__("Net payable"), money(t.net_payable))}
							${row(__("Credit ledger"), t.payable_account || "⚠ " + __("not set on the rule"))}
						</table>
						<p class="text-muted small">${frappe.utils.escape_html(t.reason || "")}</p>`;

					const d = new frappe.ui.Dialog({
						title: t.applicable ? __("TDS applicable — review the working") : __("No TDS due"),
						primary_action_label: t.applicable && t.payable_account ? __("Apply as deduction row") : __("Close"),
						primary_action: () => {
							if (t.applicable && t.payable_account) {
								const tax = frm.add_child("taxes", {
									category: "Total",
									add_deduct_tax: "Deduct",
									charge_type: "Actual",
									account_head: t.payable_account,
									description: __("TDS {0} @ {1}% on {2} (as computed at booking)", [
										t.section, t.rate, format_currency(t.tds_base, frm.doc.currency),
									]),
									tax_amount: t.tds_amount,
								});
								frm.refresh_field("taxes");
								frappe.show_alert({
									message: __("TDS row added — {0} into {1}. You can edit or remove it before saving.", [
										format_currency(t.tds_amount, frm.doc.currency), t.payable_account,
									]),
									indicator: "green",
								});
							}
							d.hide();
						},
					});
					d.$body.html(html);
					d.show();
				},
			});
		});
	},
});
