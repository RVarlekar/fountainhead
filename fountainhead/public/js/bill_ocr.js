// Bill OCR — fills the purchase form from the attached scan.
//
// Fires when the user sets `custom_attachment`. It fills:
//   * the header fields that are printed on every bill (supplier, invoice no, date)
//   * one Items row per line on the bill, carrying description, quantity and rate
//
// It deliberately does NOT choose item codes or the Item Group:
//   * Item Group decides who approves the document (PR Workflow 3 routes on it)
//   * a wrong item code corrupts stock silently, and measured against real bills
//     the top-scoring candidate is wrong often enough to rule auto-picking out
// Both are offered as one-click suggestions instead.
//
// Nothing here saves the document. The user presses Save.

frappe.provide("fountainhead.bill_ocr");

fountainhead.bill_ocr = {
	run(frm) {
		if (!frm.doc.custom_attachment) return;
		// Don't re-read the same file — each OCR call costs money.
		if (frm.__bill_ocr_last === frm.doc.custom_attachment) return;
		frm.__bill_ocr_last = frm.doc.custom_attachment;

		frm.dashboard.set_headline(__("Reading the attached bill…"));

		frappe.call({
			method: "fountainhead.bill_ocr.api.extract_bill",
			args: { file_url: frm.doc.custom_attachment, doctype: frm.doctype },
			freeze: true,
			freeze_message: __("Reading the bill…"),
			callback: (r) => {
				frm.dashboard.clear_headline();
				if (r.message) fountainhead.bill_ocr.apply(frm, r.message);
			},
			error: () => {
				frm.dashboard.clear_headline();
				frm.__bill_ocr_last = null; // allow a retry on the same file
			},
		});
	},

	apply(frm, result) {
		const filled = [];

		if (result.fields.supplier && !frm.doc.supplier) {
			frm.set_value("supplier", result.fields.supplier);
			filled.push(__("Supplier"));
		}
		if (result.fields.bill_no) {
			frm.set_value("bill_no", result.fields.bill_no);
			filled.push(__("Supplier Invoice No"));
		}
		if (result.fields.bill_date) {
			frm.set_value("bill_date", result.fields.bill_date);
			filled.push(__("Supplier Invoice Date"));
		}

		const rows = fountainhead.bill_ocr.fill_items(frm, result.items || []);
		if (rows) filled.push(__("{0} item rows", [rows]));

		frappe.show_alert({
			message: filled.length
				? __("Filled: {0}", [filled.join(", ")])
				: __("Bill read, but nothing could be filled automatically"),
			indicator: filled.length ? "green" : "orange",
		});

		fountainhead.bill_ocr.show_summary(frm, result);
	},

	// Adds one Items row per bill line with quantity and rate from the bill.
	// item_code is left empty on purpose — the dialog assigns it.
	fill_items(frm, items) {
		if (!items.length) return 0;

		// Drop the blank starter row Frappe adds, but never discard real work.
		const existing = (frm.doc.items || []).filter((d) => d.item_code);
		if (existing.length) {
			frappe.show_alert({
				message: __("Items table already has rows — leaving it alone."),
				indicator: "orange",
			});
			return 0;
		}
		frm.clear_table("items");

		items.forEach((line, i) => {
			const row = frm.add_child("items", {
				description: line.description || "",
				qty: line.quantity || 1,
				rate: line.rate || 0,
			});
			line.__rowname = row.name;
			line.__idx = i;
		});
		frm.refresh_field("items");
		return items.length;
	},

	// Set item_code on a row, then restore the bill's quantity and rate —
	// ERPNext's item_code handler refetches rate from the price list, which
	// would otherwise overwrite what the bill actually says.
	assign_item(frm, line, item_code) {
		const dt = "Purchase Receipt Item";
		return frappe.model
			.set_value(dt, line.__rowname, "item_code", item_code)
			.then(() => frappe.model.set_value(dt, line.__rowname, "qty", line.quantity || 1))
			.then(() => frappe.model.set_value(dt, line.__rowname, "rate", line.rate || 0))
			.then(() => {
				frm.refresh_field("items");
				frappe.show_alert({
					message: __("Row {0}: {1}", [line.__idx + 1, item_code]),
					indicator: "green",
				});
			})
			.catch(() => {
				frappe.show_alert({
					message: __("Could not set the item on row {0} — pick it in the Items table.", [
						line.__idx + 1,
					]),
					indicator: "red",
				});
			});
	},

	show_summary(frm, result) {
		const money = (v) =>
			v === null || v === undefined
				? "—"
				: format_currency(v, frm.doc.currency || frappe.defaults.get_default("currency"));

		const t = result.totals || {};
		const totals_rows = [
			[__("Taxable value"), money(t.taxable_value)],
			[__("CGST"), money(t.cgst)],
			[__("SGST"), money(t.sgst)],
			[__("IGST"), money(t.igst)],
			[__("Round off"), money(t.round_off)],
			[`<b>${__("Grand total")}</b>`, `<b>${money(t.grand_total)}</b>`],
		]
			.map(([k, v]) => `<tr><td>${k}</td><td class="text-right">${v}</td></tr>`)
			.join("");

		const notes = (result.notes || []).length
			? `<div class="alert alert-warning" style="margin-top:12px">
					<ul style="margin:0;padding-left:18px">
						${result.notes.map((n) => `<li>${frappe.utils.escape_html(n)}</li>`).join("")}
					</ul>
				</div>`
			: "";

		// The nature of the expense, read off the bill. Offered as a starting point
		// for the mandatory Reason for Purchase — the user still owns the wording,
		// since the real reason ("Grade 5 exam papers") is context no bill carries.
		const category = (result.suggestions || {}).expense_category;
		const reason_html =
			category && !frm.doc.custom_reason_for_purchase
				? `<div class="alert alert-info" style="margin-top:12px">
						<b>${__("Reason for Purchase")}:</b> ${frappe.utils.escape_html(category)}
						<button class="btn btn-xs btn-default bill-ocr-reason" style="margin-left:8px">
							${__("Use as starting point")}
						</button>
						<div class="small text-muted">
							${__("Read off the bill — edit it into the real reason after inserting.")}
						</div>
					</div>`
				: "";

		const suggestion = (result.suggestions || {}).custom_item_group;
		const suggestion_html = suggestion
			? `<div class="alert alert-info" style="margin-top:12px">
					<b>${__("Suggested Item Group")}:</b> ${frappe.utils.escape_html(suggestion.item_group)}
					<div class="small text-muted">
						${__("From this supplier's previous receipts — {0} of them, {1}% of their history.", [
							suggestion.seen,
							suggestion.share,
						])}
						${__("This decides who approves the document, so it is not filled in for you.")}
					</div>
				</div>`
			: "";

		// One block per bill line, with its candidate items as buttons.
		const lines_html = (result.items || [])
			.map((line, i) => {
				const cands = line.candidates || [];
				const buttons = cands.length
					? cands
							.map(
								(c) =>
									`<button class="btn btn-xs btn-default bill-ocr-pick"
										style="margin:2px 4px 2px 0"
										data-line="${i}" data-code="${frappe.utils.escape_html(c.item_code)}">
										${frappe.utils.escape_html(c.item_name || c.item_code)}
										<span class="text-muted">${c.score}%${c.seen_before ? " ·&nbsp;used&nbsp;before" : ""}</span>
									</button>`
							)
							.join("")
					: `<span class="text-muted small">${__("No similar item found — pick one in the Items table.")}</span>`;

				return `<div style="padding:8px 0;border-bottom:1px solid var(--border-color)">
					<div><b>${__("Row")} ${i + 1}.</b> ${frappe.utils.escape_html(line.description || "")}</div>
					<div class="small text-muted" style="margin:2px 0 6px">
						${__("Qty")} ${line.quantity ?? "—"} × ${money(line.rate)} = ${money(line.amount)}
					</div>
					<div>${buttons}</div>
				</div>`;
			})
			.join("");

		const d = new frappe.ui.Dialog({
			title: __("Bill read"),
			size: "large",
			primary_action_label: __("Done"),
			primary_action: () => d.hide(),
		});

		d.$body.html(`
			<p class="text-muted">${__("Read off the bill for")}
				<b>${frappe.utils.escape_html(result.vendor_name_on_bill || "—")}</b></p>
			<table class="table table-bordered table-condensed">${totals_rows}</table>
			${suggestion_html}
			${reason_html}
			${notes}
			${
				(result.items || []).length
					? `<h5 style="margin-top:16px">${__("Items")} (${result.items.length})</h5>
						<p class="text-muted small">${__(
							"Quantity and rate are already filled into the Items table. Click an item below to set that row's Item Code — the item is never chosen for you, because the wrong one would silently affect stock."
						)}</p>
						<div style="max-height:300px;overflow:auto">${lines_html}</div>`
					: ""
			}
		`);

		d.$body.on("click", ".bill-ocr-reason", function () {
			frm.set_value("custom_reason_for_purchase", category);
			$(this).prop("disabled", true).text(__("Inserted — edit it on the form"));
			frappe.show_alert({
				message: __("Reason inserted — refine it into the actual purpose."),
				indicator: "blue",
			});
		});

		d.$body.on("click", ".bill-ocr-pick", function () {
			const idx = parseInt($(this).data("line"), 10);
			const code = $(this).data("code");
			const line = result.items[idx];
			if (!line || !line.__rowname) return;
			fountainhead.bill_ocr.assign_item(frm, line, code);
			$(this)
				.closest("div")
				.find(".bill-ocr-pick")
				.removeClass("btn-primary")
				.addClass("btn-default");
			$(this).removeClass("btn-default").addClass("btn-primary");
		});

		if (suggestion) {
			d.set_secondary_action_label(__("Use {0}", [suggestion.item_group]));
			d.set_secondary_action(() => {
				frm.set_value("custom_item_group", suggestion.item_group);
				frappe.show_alert({
					message: __("Item Group set to {0}", [suggestion.item_group]),
					indicator: "green",
				});
			});
		}

		d.show();
	},
};

frappe.ui.form.on("Purchase Receipt", {
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
});

frappe.ui.form.on("Purchase Invoice", {
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
});
