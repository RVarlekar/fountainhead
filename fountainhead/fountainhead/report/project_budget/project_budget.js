// Copyright (c) 2025, GreyCube Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Project Budget"] = {
	"filters": [
		{
			'fieldname': 'project',
			'fieldtype': 'Link',
			'label': __('Project'),
			'options': 'Project',
			// 'reqd' : 1,
			'default':"Basket ball Court Area"
		},
		{
			'fieldname': 'date',
			'fieldtype': 'Date',
			'label': __('Date'),
			// 'reqd' : 1,
			'default': frappe.datetime.get_today(),
			'hidden':1
		},

	],
	onload: function(report) {
		const url = new URL(window.location.href);
		const params = new URLSearchParams(url.search);
		let queryParams = Object.fromEntries(params);
		let project_name = queryParams.project
		frappe.query_report.set_filter_value("project", project_name);
		frappe.query_report.refresh()
	}
};
