// Cash Memo numbering — for small local vendors who give no bill.
//
// The running number used to be typed by hand (a report lookup before every
// entry to find the last one; it had reached 145). One click now issues the
// next CM-#### from an atomic server-side series — no lookups, no duplicates,
// even with two people entering at once.

function add_cash_memo_button(frm) {
	if (frm.doc.docstatus !== 0) return;
	frm.add_custom_button(__("Cash Memo No."), () => {
		if (frm.doc.bill_no) {
			frappe.show_alert({
				message: __("Supplier Invoice No already has “{0}” — clear it first if this should be a cash memo.", [
					frm.doc.bill_no,
				]),
				indicator: "orange",
			});
			return;
		}
		frappe.call({
			method: "fountainhead.bill_ocr.api.next_cash_memo_number",
			callback: (r) => {
				if (!r.message) return;
				frm.set_value("bill_no", r.message.number);
				if (!frm.doc.bill_date) frm.set_value("bill_date", frappe.datetime.get_today());
				frappe.show_alert({
					message: __("Cash Memo number {0} issued.", [r.message.number]),
					indicator: "green",
				});
			},
		});
	});
}

frappe.ui.form.on("Purchase Receipt", { refresh: add_cash_memo_button });
frappe.ui.form.on("Purchase Invoice", { refresh: add_cash_memo_button });
