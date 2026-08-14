"""The vision call — the only part of this module that touches the network.

Uses `requests` (already a Frappe dependency) rather than the Anthropic SDK, so
the app adds no new Python dependency to install on staging or production.

The API key is read from site_config.json:

    bench --site <site> set-config anthropic_api_key sk-ant-...

Never commit it, and never put it in a DocType a user can read.
"""

import base64

import frappe
import requests

from fountainhead.bill_ocr.prompt import SYSTEM_PROMPT, USER_PROMPT
from fountainhead.bill_ocr.schema import TOOL

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 16000
TIMEOUT = 180

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
# Comfortably under the API's per-request ceiling once base64 inflates it by ~33%.
MAX_BYTES = 20 * 1024 * 1024


def _content_block(file_bytes, mime_type):
	data = base64.standard_b64encode(file_bytes).decode("ascii")
	if mime_type == "application/pdf":
		return {
			"type": "document",
			"source": {"type": "base64", "media_type": "application/pdf", "data": data},
		}
	if mime_type in IMAGE_TYPES:
		return {
			"type": "image",
			"source": {"type": "base64", "media_type": mime_type, "data": data},
		}
	frappe.throw(f"Bill OCR cannot read files of type {mime_type}. Attach a PDF or an image.")


def read_bill(file_bytes, mime_type):
	"""Send the bill to Claude and return the raw extracted dict.

	Forces the `emit_invoice` tool so the reply is structured JSON, never prose.
	Thinking is disabled: this is transcription, and adaptive thinking spends
	tokens against max_tokens without improving it.
	"""
	api_key = frappe.conf.get("anthropic_api_key")
	if not api_key:
		frappe.throw(
			"Bill OCR is not configured — no Anthropic API key on this site. "
			"Set it with: bench --site <site> set-config anthropic_api_key <key>"
		)

	if len(file_bytes) > MAX_BYTES:
		frappe.throw(
			f"That attachment is {len(file_bytes) / 1024 / 1024:.1f} MB. "
			f"Bill OCR accepts up to {MAX_BYTES // 1024 // 1024} MB."
		)

	payload = {
		"model": frappe.conf.get("bill_ocr_model") or DEFAULT_MODEL,
		"max_tokens": frappe.conf.get("bill_ocr_max_tokens") or DEFAULT_MAX_TOKENS,
		"system": SYSTEM_PROMPT,
		"tools": [TOOL],
		"tool_choice": {"type": "tool", "name": "emit_invoice"},
		"thinking": {"type": "disabled"},
		"messages": [
			{
				"role": "user",
				"content": [_content_block(file_bytes, mime_type), {"type": "text", "text": USER_PROMPT}],
			}
		],
	}

	# Network failures must reach the user as a plain sentence, not a traceback.
	# requests raises on timeout / DNS failure / dropped connection; without this
	# guard the form shows a raw Python stack and looks like a crash.
	try:
		response = requests.post(
			API_URL,
			headers={
				"x-api-key": api_key,
				"anthropic-version": API_VERSION,
				"content-type": "application/json",
			},
			json=payload,
			timeout=TIMEOUT,
		)
	except requests.exceptions.Timeout:
		frappe.throw(
			f"Reading the bill timed out after {TIMEOUT} seconds. "
			"Try again — large or blurry scans take longer."
		)
	except requests.exceptions.RequestException as e:
		frappe.log_error(title="Bill OCR — network error", message=f"{type(e).__name__}: {e}")
		frappe.throw(
			"Could not reach the bill-reading service. "
			"Check the internet connection and try again."
		)

	if response.status_code != 200:
		# Log the body for diagnosis but keep the key and the bill out of the user's face.
		frappe.log_error(
			title="Bill OCR — Anthropic API error",
			message=f"HTTP {response.status_code}\n{response.text[:2000]}",
		)
		if response.status_code == 429:
			frappe.throw("The bill-reading service is rate-limited right now. Wait a minute and try again.")
		if response.status_code == 529:
			frappe.throw("The bill-reading service is overloaded. Wait a minute and try again.")
		frappe.throw(f"Could not read the bill (API returned {response.status_code}). See the error log.")

	try:
		body = response.json()
	except ValueError:
		frappe.log_error(title="Bill OCR — bad response body", message=response.text[:2000])
		frappe.throw("The bill-reading service returned an unreadable response. Try again.")
	for block in body.get("content", []):
		if block.get("type") == "tool_use" and block.get("name") == "emit_invoice":
			return block.get("input") or {}, body.get("usage", {})

	frappe.log_error(title="Bill OCR — no tool call", message=str(body)[:2000])
	frappe.throw("The bill could not be transcribed — the reader returned no structured result.")
