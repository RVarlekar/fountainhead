// Read-only rulebook (19 Aug ask): "the rule should be visible in a markdown
// file… it should NOT be editable — editing only happens through development."
// The content is fountainhead/bill_ocr/RULES.md, shipped inside the app, so
// this page can only change via a code deployment.

frappe.pages["bill-ocr-rules"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bill OCR — How it works"),
		single_column: true,
	});

	page.set_secondary_action(__("Print"), () => window.print());

	frappe.call({
		method: "fountainhead.bill_ocr.api.get_rules",
		callback: (r) => {
			if (!r.message) return;
			$(page.body).html(`
				<div class="bill-ocr-rules" style="max-width:860px;margin:0 auto;padding:8px 16px 48px;
					font-size:var(--text-md);line-height:1.65">
					<div class="text-muted small" style="margin-bottom:14px">
						${__("This document ships with the software and cannot be edited on screen — it changes only through a code deployment, so what you read is what runs.")}
					</div>
					${r.message.html}
				</div>`);
		},
	});
};
