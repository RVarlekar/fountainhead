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
			// company decides the GST treatment: registered entities get tax rows,
			// unregistered ones get GST folded into the item rates (19 Aug decision).
			args: { file_url: frm.doc.custom_attachment, doctype: frm.doctype, company: frm.doc.company },
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

	apply(frm, result, opts) {
		opts = opts || {};
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

		const rows = fountainhead.bill_ocr.fill_items(frm, result.items || [], opts.replace);
		if (rows) filled.push(__("{0} item rows", [rows]));

		const tax_rows = fountainhead.bill_ocr.fill_taxes(frm, result.taxes || [], opts.replace);
		if (tax_rows) filled.push(__("GST into the Taxes table"));

		frappe.show_alert({
			message: filled.length
				? __("Filled: {0}", [filled.join(", ")])
				: __("Bill read, but nothing could be filled automatically"),
			indicator: filled.length ? "green" : "orange",
		});

		// Replay word-for-word memory: lines whose exact wording the user has
		// answered before arrive with item_code set — assign them now so
		// ERPNext fetches item name/UOM, and tell the user what happened.
		const learned = (result.items || []).filter((l) => l.item_code && l.__rowname);
		if (learned.length) {
			(async () => {
				for (const line of learned) {
					await fountainhead.bill_ocr.assign_item(frm, line, line.item_code, { silent: true });
				}
				frappe.show_alert({
					message: __("{0} item(s) filled from memory — you picked these for the same wording before.", [
						learned.length,
					]),
					indicator: "green",
				});
			})();
		}

		fountainhead.bill_ocr.show_summary(frm, result);
	},

	// Adds one Items row per bill line with quantity and rate from the bill.
	// item_code stays empty unless the wording was LEARNED — the dialog assigns it.
	fill_items(frm, items, replace) {
		if (!items.length) return 0;

		// Drop the blank starter row Frappe adds, but never discard real work —
		// except on an explicit re-read, where replacing IS the point.
		const existing = (frm.doc.items || []).filter((d) => d.item_code);
		if (existing.length && !replace) {
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

	// The bill's GST goes into Purchase Taxes and Charges — ERPNext's grand total
	// is items + this table, so leaving it empty made a 28,558 bill produce a
	// 24,202 document. Account head comes from the company's own past receipts.
	fill_taxes(frm, taxes, replace) {
		if (!taxes.length) return 0;
		const existing = (frm.doc.taxes || []).filter((t) => t.account_head);
		if (existing.length && !replace) return 0;
		frm.clear_table("taxes");
		taxes.forEach((t) => {
			frm.add_child("taxes", {
				// The payload decides the shape: a GST entity gets tax rows, a
				// non-GST entity gets one cost row into the items' expense head.
				category: t.category || "Total",
				add_deduct_tax: t.add_deduct_tax || "Add",
				charge_type: t.charge_type || "Actual",
				account_head: t.account_head,
				description: t.description,
				tax_amount: t.tax_amount,
			});
		});
		frm.refresh_field("taxes");
		return taxes.length;
	},

	// Set item_code on a row, then restore the bill's quantity and rate —
	// ERPNext's item_code handler refetches rate from the price list, which
	// would otherwise overwrite what the bill actually says.
	assign_item(frm, line, item_code, opts) {
		opts = opts || {};
		const dt = "Purchase Receipt Item";
		return frappe.model
			.set_value(dt, line.__rowname, "item_code", item_code)
			.then(() => frappe.model.set_value(dt, line.__rowname, "qty", line.quantity || 1))
			.then(() => frappe.model.set_value(dt, line.__rowname, "rate", line.rate || 0))
			.then(() => {
				frm.refresh_field("items");
				if (!opts.silent) {
					frappe.show_alert({
						message: __("Row {0}: {1}", [line.__idx + 1, item_code]),
						indicator: "green",
					});
				}
				// Learn from MANUAL picks only — an auto-applied memory must not
				// reinforce itself.
				if (opts.remember) {
					frappe.call({
						method: "fountainhead.bill_ocr.api.remember_item_choice",
						args: {
							description: line.description,
							description_en: line.description_en,
							item_code: item_code,
						},
						// fire-and-forget; learning failure must never disturb entry
						callback: () => {},
					});
				}
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

		// Will the filled document tally with the bill? Shown FIRST, because a
		// mismatch means something was misread and everything below it is suspect.
		const p = result.projection || {};
		// The GST term shows whenever it books on top of the lines — as tax rows
		// (GST entity) or as a cost row into the items' expense head (non-GST).
		const show_gst = p.gst_total && !p.lines_tax_inclusive;
		const folded_note = p.gst_in_cost
			? `<div class="small" style="margin-top:4px">${__(
					"GST of {0} is booked as part of item cost — one charge row into the items' expense head. Item rates stay exactly as printed; no GST ledger is touched.",
					[money(p.gst_total)]
			  )}</div>`
			: "";
		// Per-page totals: on a failed tally of a multi-page scan, this is what
		// exposes a missing page ("page 1 totals 6,300, page 2 totals 14,900…").
		const pages_html =
			!p.tallies && (p.pages || []).length
				? `<div class="small" style="margin-top:6px"><b>${__("Per page")}:</b> ${p.pages
						.map((pg) =>
							__("page {0}: {1} line(s), {2}", [
								pg.page,
								pg.lineCount || "?",
								pg.itemsSubtotal != null ? money(pg.itemsSubtotal) : "?",
							])
						)
						.join(" · ")}${
						p.page_count_printed
							? ` — ${__("bill prints “{0}”", [frappe.utils.escape_html(p.page_count_printed)])}`
							: ""
				  }<br>${__("If the paper bill has more pages than were scanned, rescan the full bill and attach it again.")}</div>`
				: "";
		const tally_html =
			p.bill_grand != null
				? p.tallies
					? `<div class="alert alert-success" style="margin-top:12px">
							✓ ${__("Tallies: the rows will total {0}{1}{2} = {3}, and the bill prints {3}.", [
								money(p.items_total),
								show_gst ? " + GST " + money(p.gst_total) : "",
								p.round_off ? " " + (p.round_off > 0 ? "+" : "−") + " " + money(Math.abs(p.round_off)) : "",
								money(p.bill_grand),
							])}${folded_note}</div>`
					: `<div class="alert alert-danger" style="margin-top:12px">
							<b>✗ ${__("Does not tally.")}</b>
							${__("The rows will total {0}{1} = {2}, but the bill prints {3}.", [
								money(p.items_total),
								show_gst ? " + GST " + money(p.gst_total) : "",
								money(p.expected_grand),
								money(p.bill_grand),
							])}
							${__("Something was misread or missed — say what, below, and it will be re-read.")}
							${pages_html}
						</div>`
				: "";

		const notes = (result.notes || []).length
			? `<div class="alert alert-warning" style="margin-top:12px">
					<ul style="margin:0;padding-left:18px">
						${result.notes.map((n) => `<li>${frappe.utils.escape_html(n)}</li>`).join("")}
					</ul>
				</div>`
			: "";

		// Plain-English correction box: the user says what's wrong in their own
		// words ("the 2,250 is a 20% supervision charge, not a work line") and the
		// bill is re-read with that as reviewer instruction. Costs one fresh read.
		// COLLAPSED by default — most bills are fine, so it stays out of the way
		// until the user reaches for it.
		const feedback_html = `
			<div style="margin-top:12px; border:1px dashed var(--border-color); border-radius:6px">
				<div class="bill-ocr-fb-toggle" style="padding:9px 12px; cursor:pointer; user-select:none">
					<span class="bill-ocr-fb-arrow" style="display:inline-block; transition:transform .15s">▸</span>
					<b style="margin-left:5px">${__("Something wrong or missing?")}</b>
					<span class="small text-muted"> — ${__("tap to describe it and re-read")}</span>
				</div>
				<div class="bill-ocr-fb-body" style="display:none; padding:0 12px 12px">
					<div class="small text-muted" style="margin-bottom:6px">
						${__("Describe it in plain words — e.g. “the 2,250 is a 20% supervision charge on the labour total”. The bill will be re-read with your correction (takes ~10s, replaces the rows).")}
					</div>
					<textarea class="form-control bill-ocr-feedback" rows="2"
						placeholder="${__("What did it get wrong?")}"></textarea>
					<button class="btn btn-sm btn-default bill-ocr-reread" style="margin-top:6px">
						${__("Re-read with this correction")}
					</button>
				</div>
			</div>`;

		// The nature of the expense, read off the bill. Offered as a starting point
		// for the mandatory Reason for Purchase — the user still owns the wording,
		// since the real reason ("Grade 5 exam papers") is context no bill carries.
		// The button TOGGLES: insert ↔ undo (restores whatever was there before).
		const category = (result.suggestions || {}).expense_category;
		const reason_html = category
			? `<div class="alert alert-info" style="margin-top:12px">
					<b>${__("Reason for Purchase")}:</b> ${frappe.utils.escape_html(category)}
					<button class="btn btn-xs btn-default bill-ocr-reason" style="margin-left:8px">
						${__("Use as starting point")}
					</button>
					<div class="small text-muted">
						${__("Read off the bill — edit it into the real reason after inserting. Click again to undo.")}
					</div>
				</div>`
			: "";

		// Item Group: the header holds exactly ONE group and it decides the
		// approver. A supplier whose history spans groups gets each meaningful
		// group as its own button — for a mixed bill the user must decide which
		// approval chain this document goes down. Buttons toggle (apply ↔ undo).
		const suggestion = (result.suggestions || {}).custom_item_group;
		const group_options = suggestion
			? [suggestion, ...(suggestion.others || [])]
			: [];
		const suggestion_html = group_options.length
			? `<div class="alert alert-info" style="margin-top:12px">
					<b>${__("Suggested Item Group")}</b>
					<span class="small text-muted">— ${__("decides who approves; not filled in for you. Click to apply, click again to undo.")}</span><br>
					${group_options
						.map(
							(g) => `<button class="btn btn-xs btn-default bill-ocr-group" style="margin:6px 6px 0 0"
								data-group="${frappe.utils.escape_html(g.item_group)}">
								${__("Use")} ${frappe.utils.escape_html(g.item_group)}
								<span class="text-muted">${g.share}% · ${g.seen}×</span>
							</button>`
						)
						.join("")}
					${
						group_options.length > 1
							? `<div class="small text-muted" style="margin-top:5px">${__(
									"This supplier's history spans more than one group. If the bill mixes them, pick the group whose approver should own this document."
							  )}</div>`
							: ""
					}
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
									c.basis === "learned"
										? `<span class="text-muted">✓ ${__("you taught this — auto-filled")}</span>`
										: c.basis === "usual"
										? `<span class="text-muted">· ${__("their usual, {0}×", [
												c.times_used,
										  ])}</span>`
										: `<span class="text-muted">${c.score}%${
												c.times_used
													? " ·&nbsp;" + __("used {0}×", [c.times_used])
													: ""
										  }</span>`;
								const applied = c.basis === "learned" && line.item_code === c.item_code;
								return `<button class="btn btn-xs ${applied ? "btn-primary" : "btn-default"} bill-ocr-pick"
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

				const charge_tag = line.is_charge
					? ` <span class="indicator-pill orange" style="font-size:11px">${__(
							"charge on top of items"
					  )}</span>`
					: "";

				return `<div style="padding:8px 0;border-bottom:1px solid var(--border-color)">
					<div><b>${__("Row")} ${i + 1}.</b> ${frappe.utils.escape_html(line.description || "")}${charge_tag}</div>
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
			// The reload: "something looks off but I can't name it". Reads the bill
			// again from scratch in careful mode — cache bypassed, every digit and
			// spelling re-verified — and REPLACES the rows with the new reading.
			// (When the user CAN name the problem, the correction box below is
			// better: their words steer the re-read.)
			secondary_action_label: __("↻ Read again, carefully"),
			secondary_action: () => {
				frappe.call({
					method: "fountainhead.bill_ocr.api.reread_bill",
					args: { file_url: frm.doc.custom_attachment, doctype: frm.doctype, company: frm.doc.company },
					freeze: true,
					freeze_message: __("Re-reading the bill carefully — every figure re-verified…"),
					callback: (r) => {
						if (!r.message) return;
						d.hide();
						fountainhead.bill_ocr.apply(frm, r.message, { replace: true });
					},
				});
			},
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
			${tally_html}
			${suggestion_html}
			${reason_html}
			${notes}
			${
				(result.items || []).length
					? `<h5 style="margin-top:16px">${__("Items")} (${result.items.length})</h5>
						<p class="text-muted small">${__(
							"Quantity and rate are already filled into the Items table. Click an item below to set that row's Item Code — your choice is remembered, and next time the same wording is filled in automatically."
						)}</p>
						<div style="max-height:300px;overflow:auto">${lines_html}</div>`
					: ""
			}
			${feedback_html}
		`);

		// Reason: TOGGLE — insert, or click again to restore what was there before.
		let reason_prev = null;
		let reason_applied = false;
		d.$body.on("click", ".bill-ocr-reason", function () {
			if (!reason_applied) {
				reason_prev = frm.doc.custom_reason_for_purchase || "";
				frm.set_value("custom_reason_for_purchase", category);
				reason_applied = true;
				$(this).removeClass("btn-default").addClass("btn-primary").text(__("Undo — restore previous"));
				frappe.show_alert({ message: __("Reason inserted — refine it into the actual purpose."), indicator: "blue" });
			} else {
				frm.set_value("custom_reason_for_purchase", reason_prev);
				reason_applied = false;
				$(this).removeClass("btn-primary").addClass("btn-default").text(__("Use as starting point"));
				frappe.show_alert({ message: __("Reason restored."), indicator: "blue" });
			}
		});

		// Item Group buttons: apply one (others reset), click the applied one to undo.
		// The label states the mode explicitly — "Use X" when idle, "✓ Using X — tap
		// to undo" when applied — so the state is readable without knowing the colours.
		let group_prev = null;
		let group_applied = null;
		const reset_group_btns = () => {
			d.$body.find(".bill-ocr-group").each(function () {
				const orig = $(this).data("orig");
				if (orig) $(this).html(orig);
				$(this).removeClass("btn-primary").addClass("btn-default");
			});
		};
		d.$body.on("click", ".bill-ocr-group", function () {
			const g = $(this).data("group");
			if (!$(this).data("orig")) $(this).data("orig", $(this).html());
			if (group_applied === g) {
				frm.set_value("custom_item_group", group_prev);
				group_applied = null;
				reset_group_btns();
				frappe.show_alert({ message: __("Item Group restored to “{0}”.", [group_prev || __("empty")]), indicator: "blue" });
				return;
			}
			if (group_applied === null) group_prev = frm.doc.custom_item_group || "";
			frm.set_value("custom_item_group", g);
			group_applied = g;
			reset_group_btns();
			$(this)
				.removeClass("btn-default")
				.addClass("btn-primary")
				.html(`✓ ${__("Using")} ${frappe.utils.escape_html(g)} — ${__("tap to undo")}`);
			frappe.show_alert({ message: __("Item Group set to {0}.", [g]), indicator: "green" });
		});

		// Collapsible correction section.
		d.$body.on("click", ".bill-ocr-fb-toggle", function () {
			const body = d.$body.find(".bill-ocr-fb-body");
			const open = body.is(":visible");
			body.slideToggle(120);
			d.$body.find(".bill-ocr-fb-arrow").css("transform", open ? "rotate(0deg)" : "rotate(90deg)");
			if (!open) setTimeout(() => d.$body.find(".bill-ocr-feedback").focus(), 150);
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
			// A manual pick is a human decision — remember it for next time.
			fountainhead.bill_ocr.assign_item(frm, line, code, { remember: true });
			$(this)
				.closest("div")
				.find(".bill-ocr-pick")
				.removeClass("btn-primary")
				.addClass("btn-default");
			$(this).removeClass("btn-default").addClass("btn-primary");
		});

		// Plain-English correction → re-read → replace the rows with the new reading.
		d.$body.on("click", ".bill-ocr-reread", function () {
			const feedback = (d.$body.find(".bill-ocr-feedback").val() || "").trim();
			if (!feedback) {
				frappe.show_alert({ message: __("Write what is wrong first."), indicator: "orange" });
				return;
			}
			frappe.call({
				method: "fountainhead.bill_ocr.api.reinterpret_bill",
				args: {
					file_url: frm.doc.custom_attachment,
					doctype: frm.doctype,
					feedback: feedback,
					company: frm.doc.company,
				},
				freeze: true,
				freeze_message: __("Re-reading the bill with your correction…"),
				callback: (r) => {
					if (!r.message) return;
					d.hide();
					// Replace: this is an explicit re-read, so the old rows go.
					fountainhead.bill_ocr.apply(frm, r.message, { replace: true });
				},
			});
		});

		d.show();
	},
};

// onload_post_render covers forms that ARRIVE with an attachment already set —
// the batch queue's "Create Purchase Receipt" button routes here with the file
// in route_options, which does not fire the field-change trigger.
// "View bill" — the original scan, one click from the document (and therefore
// one click from its ledger entries: GL → voucher → here). The Invoice inherits
// the Receipt's attachment server-side, so the trail survives PR → PI.
function bill_ocr_view_button(frm) {
	if (!frm.doc.custom_attachment || frm.is_new()) return;
	frm.add_custom_button(__("📄 View bill"), () => {
		window.open(frm.doc.custom_attachment, "_blank", "noopener");
	});
}

frappe.ui.form.on("Purchase Receipt", {
	refresh: bill_ocr_view_button,
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
	onload_post_render(frm) {
		if (frm.is_new() && frm.doc.custom_attachment) fountainhead.bill_ocr.run(frm);
	},
});

frappe.ui.form.on("Purchase Invoice", {
	refresh: bill_ocr_view_button,
	custom_attachment(frm) {
		fountainhead.bill_ocr.run(frm);
	},
	onload_post_render(frm) {
		if (frm.is_new() && frm.doc.custom_attachment) fountainhead.bill_ocr.run(frm);
	},
});
