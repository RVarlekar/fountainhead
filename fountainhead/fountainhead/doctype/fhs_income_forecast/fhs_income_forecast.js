// Copyright (c) 2025, GreyCube Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("FHS Income Forecast", {
	setup(frm) {
        frm.set_query('income_account', function() {
            return {
                filters : {
                    'account_type': 'Income Account',
                    'company' : frappe.defaults.get_user_defaults("Company")[0],
                    'is_group' : 0,
                }
            }
        });
	},

    refresh(frm) {
        if (frm.is_new() == undefined) {
            frm.add_custom_button(__('Income Variance Report'), () => show_income_variance_report_from_income_forecast(frm))
            .css({'background-color':'#87CEFA','font-weight': 'bold','color':'#fff'});
        }
    },

    load_all_grades: function(frm) {
        if (frm.is_dirty() == true){
            frappe.throw({
                message: __('Please Save Form To Proceed'),
                indicator: 'red'
            })
        }
        
        // Calling Python Function To Load All Grades.
        frappe.call({
            method: 'load_all_grades',
            doc : frm.doc,
        })
    }
});

function show_income_variance_report_from_income_forecast(frm) {
    frappe.open_in_new_tab = true;
    frappe.route_options = {
        income_account: frm.doc.income_account
    };                    
    frappe.set_route("query-report", "Income Variance");
}

frappe.ui.form.on("Income Forecast Details", {
    total_grade_discount: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn]
        if (row.total_grade_discount > 0 && row.annual_fees > 0) {
            let amount_after_discount = row.annual_fees - row.total_grade_discount;
            frappe.model.set_value(cdt, cdn, "fees_amount_after_discount", amount_after_discount);
        }
    }
})