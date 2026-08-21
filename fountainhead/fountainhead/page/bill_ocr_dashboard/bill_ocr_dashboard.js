// Manager dashboard (19 Aug ask): how many bills uploaded, deleted, late —
// and the reading cost shown NEXT TO the time it saved, "so that when you show
// them the ₹2-per-bill cost, you also show the time saved beside it".

frappe.pages["bill-ocr-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bill OCR — Dashboard"),
		single_column: true,
	});

	page.set_secondary_action(__("Refresh"), () => render(page));
	render(page);
};

function render(page) {
	frappe.call({
		method: "fountainhead.bill_ocr.api.dashboard_stats",
		callback: (r) => {
			const s = r.message;
			if (!s) return;
			const inr = (v) => format_currency(v, "INR");
			const card = (label, value, sub, color) => `
				<div style="flex:1 1 150px;min-width:150px;border:1px solid var(--border-color);
					border-radius:8px;padding:14px 16px;background:var(--card-bg)">
					<div class="text-muted small">${label}</div>
					<div style="font-size:1.6em;font-weight:600;color:${color || "inherit"}">${value}</div>
					${sub ? `<div class="text-muted small">${sub}</div>` : ""}
				</div>`;

			const st = s.by_status || {};
			const hours = Math.floor(s.minutes_saved / 60);
			const mins = s.minutes_saved % 60;

			const users = (s.per_user || [])
				.map((u) => `<tr><td>${frappe.utils.escape_html(u.user)}</td><td class="text-right">${u.count}</td></tr>`)
				.join("");
			const errors = (s.errors || [])
				.map(
					(e) => `<tr>
						<td><a href="/app/bill-ocr-upload/${encodeURIComponent(e.name)}">${e.name}</a></td>
						<td>${frappe.utils.escape_html(e.vendor_name || "—")}</td>
						<td class="text-muted">${frappe.utils.escape_html((e.error_message || "").slice(0, 80))}</td>
					</tr>`
				)
				.join("");

			$(page.body).html(`
				<div style="max-width:1000px;margin:0 auto;padding:8px 16px 48px">
					<h5>${__("Queue")}</h5>
					<div style="display:flex;gap:12px;flex-wrap:wrap">
						${card(__("Total bills uploaded"), s.total, __("{0} this month", [s.uploads_this_month]))}
						${card(__("Pending"), st["Pending"] || 0, "", "var(--orange-500)")}
						${card(__("Read, awaiting receipt"), st["Read"] || 0, "", "var(--green-600)")}
						${card(__("Receipt created"), st["Receipt created"] || 0, "", "var(--blue-500)")}
						${card(__("Errors"), st["Error"] || 0, "", st["Error"] ? "var(--red-500)" : "")}
					</div>
					<h5 style="margin-top:22px">${__("Attention")}</h5>
					<div style="display:flex;gap:12px;flex-wrap:wrap">
						${card(__("Late bills in queue"), s.late_pending,
							__("dated before {0}", [frappe.datetime.str_to_user(s.window_start)]),
							s.late_pending ? "var(--red-500)" : "var(--green-600)")}
						${card(__("Deleted uploads"), s.deleted, __("all time"))}
					</div>
					<h5 style="margin-top:22px">${__("Cost — always beside the time it saved")}</h5>
					<div style="display:flex;gap:12px;flex-wrap:wrap">
						${card(__("Bills read"), s.reads, __("readings paid for"))}
						${card(__("Reading cost"), inr(s.cost_inr), __("≈ {0} per bill", [inr(s.cost_per_read)]))}
						${card(__("Typing time saved"), `${hours}h ${mins}m`, __("at 3–5 min per bill"), "var(--green-600)")}
						${card(__("Value of that time"), "≈ " + inr(s.value_saved_inr), __("at ₹200/hour"), "var(--green-600)")}
					</div>
					<div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:22px">
						<div style="flex:1;min-width:280px">
							<h5>${__("Uploads by person")}</h5>
							<table class="table table-bordered table-condensed">
								<thead><tr><th>${__("User")}</th><th class="text-right">${__("Bills")}</th></tr></thead>
								<tbody>${users || `<tr><td colspan=2 class="text-muted">${__("None yet")}</td></tr>`}</tbody>
							</table>
						</div>
						<div style="flex:2;min-width:320px">
							<h5>${__("Recent errors")}</h5>
							<table class="table table-bordered table-condensed">
								<thead><tr><th>${__("Row")}</th><th>${__("Vendor")}</th><th>${__("Error")}</th></tr></thead>
								<tbody>${errors || `<tr><td colspan=3 class="text-muted">${__("None")} 🎉</td></tr>`}</tbody>
							</table>
						</div>
					</div>
				</div>`);
		},
	});
}
