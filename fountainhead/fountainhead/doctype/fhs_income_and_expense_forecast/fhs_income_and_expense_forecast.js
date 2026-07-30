// Copyright (c) 2025, GreyCube Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("FHS Income And Expense Forecast", {
    fetch_accounts: function (frm) {
        if (frm.is_dirty() == true) {
            frappe.throw({
                message: __('Please Save Form To Proceed'),
                indicator: 'red'
            })
        }

        frappe.call({
            method: 'fetch_eligible_profit_and_loss_accounts',
            doc: frm.doc,
        })
    },

    refresh(frm) {
        if (frm.is_new() == undefined) {
            frm.add_custom_button(__('Income & Expense Budget Vs Actual'), () => show_income_and_expense_budget_vs_actual_report_from_ie_forecast(frm))
            .css({'background-color':'#87CEFA','font-weight': 'bold','color':'#fff'});
        }
    },
});

function show_income_and_expense_budget_vs_actual_report_from_ie_forecast(frm) {
    frappe.open_in_new_tab = true;
    frappe.route_options = {
        company: frm.doc.company,
        fiscal_year: frm.doc.fiscal_year
    };                    
    frappe.set_route("query-report", "Income & Expense Budget Vs Actual");
}