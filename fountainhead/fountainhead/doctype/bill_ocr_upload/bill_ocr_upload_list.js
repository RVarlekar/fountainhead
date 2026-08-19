// Batch entry point: upload a whole folder of bills, then read them in sequence.
//
// Reading runs from the browser one bill at a time (like the standalone
// prototype's queue) — no background workers involved, so the batch behaves the
// same on a dev bench and on staging, shows live progress, and stops cleanly if
// the tab is closed.

frappe.listview_settings["Bill OCR Upload"] = {
	hide_name_column: true,

	onload(listview) {
		listview.page.add_inner_button(__("Upload bills"), () => {
			new frappe.ui.FileUploader({
				allow_multiple: true,
				restrictions: {
					allowed_file_types: ["image/jpeg", "image/png", "image/webp", "application/pdf"],
				},
				on_success(file) {
					// One queue row per uploaded file.
					frappe.db
						.insert({ doctype: "Bill OCR Upload", bill_file: file.file_url })
						.then(() => listview.refresh());
				},
			});
		});

		// NOTE: the handler must NOT return a promise — Frappe disables an inner
		// button while a returned promise is pending, and it never re-enabled
		// after the first batch. Fire-and-forget keeps the button always usable;
		// the guard below stops two batches running at once.
		let batch_running = false;
		const read_all_pending = async () => {
			if (batch_running) {
				frappe.show_alert({ message: __("A batch is already running."), indicator: "orange" });
				return;
			}
			batch_running = true;
			let done = 0,
				failed = 0;
			try {
				const pending = await frappe.db.get_list("Bill OCR Upload", {
					filters: { status: "Pending" },
					fields: ["name"],
					limit: 200,
					order_by: "creation asc",
				});
				if (!pending.length) {
					frappe.show_alert({ message: __("Nothing pending."), indicator: "blue" });
					return;
				}
				for (const row of pending) {
					frappe.show_progress(
						__("Reading bills"),
						done + failed,
						pending.length,
						__("{0} of {1} — each takes ~8 seconds", [done + failed + 1, pending.length])
					);
					try {
						const r = await frappe.call({
							method: "fountainhead.bill_ocr.api.read_upload",
							args: { name: row.name },
						});
						(r.message || {}).status === "Error" ? failed++ : done++;
					} catch (e) {
						failed++;
					}
				}
				frappe.msgprint(
					__("Batch finished: {0} read, {1} failed. Failed rows show their error — open them to retry.", [
						done,
						failed,
					])
				);
			} finally {
				// Always clear the progress bar and re-arm the button, even if the
				// list query itself failed mid-way.
				frappe.hide_progress();
				batch_running = false;
				listview.refresh();
			}
		};

		listview.page.add_inner_button(__("Read all pending"), () => {
			read_all_pending();
		});
	},

	get_indicator(doc) {
		return {
			Pending: [__("Pending"), "orange", "status,=,Pending"],
			Read: [__("Read"), "green", "status,=,Read"],
			Error: [__("Error"), "red", "status,=,Error"],
		}[doc.status];
	},
};
