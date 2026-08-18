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

	// Deliberate mini-form for adding an item that doesn't exist yet.
	// Not a one-click button, on purpose: 2,291 of the 6,141 items in this system
	// were created in the last year and it already contains typo-duplicates like
	// "Foam Roller 6" / "Fuam Roller 6". Every new item must be a decision.
	create_item(frm, line, result) {
		const d = line.create_defaults || {};
		const stock = d.stock || {};

		const dlg = new frappe.ui.Dialog({
			title: __("Create a new item"),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "src",
					options: `<div class="alert alert-warning" style="margin-bottom:12px">
						<b>${__("On the bill")}:</b> ${frappe.utils.escape_html(line.description || "")}
						${
							line.is_translated
								? `<div class="small" style="margin-top:4px">${__("English")}:
									<b>${frappe.utils.escape_html(line.description_en || "")}</b></div>`
								: ""
						}
					</div>`,
				},
				{
					fieldtype: "Data",
					fieldname: "item_name",
					label: __("Item name"),
					reqd: 1,
					default: d.item_name || line.description_en || line.description,
					description: __("Taken from the bill. Edit it to match how your master names things."),
				},
				{
					fieldtype: "Link",
					fieldname: "item_group",
					label: __("Item Group"),
					options: "Item Group",
					reqd: 1,
					default: d.item_group || frm.doc.custom_item_group,
					onchange() {
						const g = this.get_value();
						if (!g) return;
						frappe.call({
							method: "fountainhead.bill_ocr.api.get_creation_defaults",
							args: { item_group: g, unit: d.uom_on_bill },
							callback: (r) => {
								if (!r.message) return;
								const s = r.message.stock || {};
								dlg.set_value("is_stock_item", s.is_stock_item ? 1 : 0);
								dlg.get_field("is_stock_item").set_description(
									s.basis ? __("Based on history: {0}", [s.basis]) : ""
								);
							},
						});
					},
				},
				{
					fieldtype: "Link",
					fieldname: "stock_uom",
					label: __("Unit of Measure"),
					options: "UOM",
					reqd: 1,
					default: d.stock_uom || "Number",
					description: d.uom_on_bill
						? __("Bill says “{0}”.", [d.uom_on_bill])
						: __("The bill did not state a unit."),
				},
				{
					fieldtype: "Check",
					fieldname: "is_stock_item",
					label: __("This is a stock item (it goes into inventory)"),
					default: stock.is_stock_item ? 1 : 0,
					description: stock.basis
						? __("Based on history: {0}", [stock.basis]) +
						  (stock.certain ? "" : "  ⚠ " + __("this group is mixed — please check"))
						: "",
				},
				{ fieldtype: "HTML", fieldname: "similar" },
			],
			primary_action_label: __("Create item"),
			primary_action: (v) => fountainhead.bill_ocr._do_create(frm, line, result, dlg, v, 0),
		});
		dlg.show();
	},

	_do_create(frm, line, result, dlg, values, acknowledged) {
		frappe.call({
			method: "fountainhead.bill_ocr.api.create_item_from_bill",
			args: {
				item_name: values.item_name,
				item_group: values.item_group,
				stock_uom: values.stock_uom,
				is_stock_item: values.is_stock_item ? 1 : 0,
				description: line.description,
				source_note: `${result.supplier?.supplier || result.vendor_name_on_bill || ""} — ${
					result.fields?.bill_no || ""
				}`,
				acknowledged_similar: acknowledged,
			},
			freeze: true,
			freeze_message: __("Creating item…"),
			callback: (r) => {
				const m = r.message || {};
				if (m.needs_confirmation) {
					// Show what already exists BEFORE allowing a duplicate.
					const rows = (m.similar || [])
						.map(
							(s) => `<li style="margin:4px 0">
								<button class="btn btn-xs btn-default bill-ocr-useexisting"
									data-code="${frappe.utils.escape_html(s.item_code)}">
									${__("Use this")}
								</button>
								<b>${frappe.utils.escape_html(s.item_name)}</b>
								<span class="text-muted">${s.score}% · ${frappe.utils.escape_html(s.item_group || "")}</span>
							</li>`
						)
						.join("");
					dlg.get_field("similar").$wrapper.html(
						`<div class="alert alert-danger" style="margin-top:10px">
							<b>${__("Did you mean one of these?")}</b>
							<div class="small">${__(
								"These already exist. Creating a near-duplicate makes the item master harder to use for everyone."
							)}</div>
							<ul style="margin:8px 0 0 0;padding-left:18px">${rows}</ul>
							<button class="btn btn-xs btn-danger bill-ocr-forcecreate" style="margin-top:6px">
								${__("None of these — create it anyway")}
							</button>
						</div>`
					);
					dlg.get_field("similar").$wrapper.find(".bill-ocr-useexisting").on("click", function () {
						fountainhead.bill_ocr.assign_item(frm, line, $(this).data("code"));
						dlg.hide();
					});
					dlg.get_field("similar").$wrapper.find(".bill-ocr-forcecreate").on("click", () =>
						fountainhead.bill_ocr._do_create(frm, line, result, dlg, values, 1)
					);
					return;
				}
				if (m.created) {
					fountainhead.bill_ocr.assign_item(frm, line, m.item_code);
					dlg.hide();
				}
			},
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
				// Two kinds of suggestion, labelled differently because they mean
				// different things: a text match is "this reads like that item",
				// whereas "their usual" is "this supplier is nearly always billed
				// for that". A raw percentage would make them look comparable.
				const buttons = cands.length
					? cands
							.map((c) => {
								const tag =
									c.basis === "usual"
										? `<span class="text-muted">· ${__("their usual, {0}×", [
												c.times_used,
										  ])}</span>`
										: `<span class="text-muted">${c.score}%${
												c.times_used
													? " ·&nbsp;" + __("used {0}×", [c.times_used])
													: ""
										  }</span>`;
								return `<button class="btn btn-xs btn-default bill-ocr-pick"
										style="margin:2px 4px 2px 0"
										data-line="${i}" data-code="${frappe.utils.escape_html(c.item_code)}">
										${frappe.utils.escape_html(c.item_name || c.item_code)} ${tag}
									</button>`;
							})
							.join("")
					: `<span class="text-muted small">${__("Nothing similar in the item master.")}</span>`;

				// Always offer creation — it is the only way out for a line like Row 6
				// where the item genuinely does not exist yet.
				const create_btn = result.can_create_item
					? `<button class="btn btn-xs btn-primary bill-ocr-create"
							style="margin:2px 4px 2px 0" data-line="${i}">
							+ ${__("Create this item")}
						</button>`
					: `<span class="text-muted small">${__(
							"(you do not have permission to create items)"
					  )}</span>`;

				// Gujarati/Hindi lines show the original AND the English reading.
				const translated = line.is_translated
					? `<div class="small" style="margin-top:2px">
							<span class="text-muted">${__("English")}:</span>
							<b>${frappe.utils.escape_html(line.description_en || "")}</b>
						</div>`
					: "";

				return `<div style="padding:8px 0;border-bottom:1px solid var(--border-color)">
					<div><b>${__("Row")} ${i + 1}.</b> ${frappe.utils.escape_html(line.description || "")}</div>
					${translated}
					<div class="small text-muted" style="margin:2px 0 6px">
						${__("Qty")} ${line.quantity ?? "—"} × ${money(line.rate)} = ${money(line.amount)}
					</div>
					<div>${buttons} ${create_btn}</div>
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
				<b>${frappe.utils.escape_html(result.vendor_name_on_bill || "—")}</b>
				${
					// Show the English reading beside a non-Latin name — it is what the
					// supplier match actually ran against, so it must be checkable.
					result.vendor_name_english &&
					result.vendor_name_english !== result.vendor_name_on_bill
						? `<span>(${frappe.utils.escape_html(result.vendor_name_english)})</span>`
						: ""
				}</p>
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

		d.$body.on("click", ".bill-ocr-create", function () {
			const line = result.items[parseInt($(this).data("line"), 10)];
			if (line) fountainhead.bill_ocr.create_item(frm, line, result);
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

// onload_post_render covers forms that ARRIVE with an attachment already set —
// the batch queue's "Create Purchase Receipt" button routes here with the file
// in route_options, which does not fire the field-change trigger.
frappe.ui.form.on("Purchase Receipt", {
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
	onload_post_render(frm) {
		if (frm.is_new() && frm.doc.custom_attachment) fountainhead.bill_ocr.run(frm);
	},
});

frappe.ui.form.on("Purchase Invoice", {
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
	onload_post_render(frm) {
		if (frm.is_new() && frm.doc.custom_attachment) fountainhead.bill_ocr.run(frm);
	},
});
