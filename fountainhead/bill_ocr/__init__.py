"""Bill OCR — read a scanned vendor bill and pre-fill the purchase form.

Design (settled with Vardan sir and Ashlesha ma'am, Aug 2026):

  * The trigger is the `custom_attachment` field already on Purchase Receipt and
    Purchase Invoice. No new button, no separate app.
  * This module NEVER creates, saves or submits a document. It returns extracted
    values to the browser, which fills the form the user is already looking at.
    The user checks the numbers and presses Save.

Why it must work that way: `custom_item_group` and `custom_reason_for_purchase`
are mandatory on Purchase Receipt and appear on no vendor bill, so a background
job that tried to create a draft would fail its save every single time.

`custom_item_group` is offered as a SUGGESTION only, never auto-applied — it is
the field `PR Workflow 3` routes approvals on, so a silent wrong guess sends the
document to the wrong approver.
"""
