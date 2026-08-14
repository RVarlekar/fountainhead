"""Match what was read off the bill against the ERPNext masters.

Nothing here creates a master record. An unmatched supplier comes back as a
suggestion list for the user to pick from, or to create deliberately — never
silently, because a duplicate supplier is far more expensive to unpick later
than a moment spent choosing.

Measured against the 3,299 real Purchase Receipts in the July 2026 data:

  * item group taken from the first line item's own group : 17.7% correct
  * item group taken from the supplier's usual group      : 84.0% correct

which is why `suggest_item_group` keys off supplier history and not the items.
386 of the 453 suppliers ever used on a receipt only use a single group.
"""

import re

import frappe

# Below this, a name match is too weak to offer as the top pick.
FUZZY_ACCEPT = 82.0
FUZZY_SUGGEST = 60.0

_NOISE = re.compile(
	r"\b(pvt|private|ltd|limited|llp|inc|co|company|corp|corporation|and|the|"
	r"enterprise|enterprises|traders|trading|agency|agencies|industries|"
	r"industry|sons|bros|brothers)\b",
	re.I,
)


_LATIN_IN_BRACKETS = re.compile(r"\(([A-Za-z][A-Za-z\s.&'-]{2,})\)")
_NON_LATIN = re.compile(r"[^\x00-\x7F]")


def latinise(value):
	"""Pull the usable Latin form out of a vendor name.

	Gujarati bills come back from the reader as
	`દિપક સ્ટેશનરી માર્ટ (Deepak Stationery Mart)` — the script, then a
	transliteration in brackets. The supplier master is entirely Latin
	(`DEEPAK STATIONERY MART`), so matching on the raw string finds nothing.
	Take the bracketed transliteration when the name carries non-Latin script.
	"""
	if not value:
		return ""
	s = str(value)
	if _NON_LATIN.search(s):
		m = _LATIN_IN_BRACKETS.search(s)
		if m:
			return m.group(1).strip()
		# No transliteration offered — strip the script and hope for a remainder.
		return _NON_LATIN.sub(" ", s).strip(" ()")
	return s


def normalize_name(value):
	s = latinise(value).lower()
	if not s:
		return ""
	s = re.sub(r"[^\w\s]", " ", s)
	s = _NOISE.sub(" ", s)
	return re.sub(r"\s+", " ", s).strip()


def name_tokens(value):
	"""Word tokens for a party name, minus initials.

	Single letters are dropped so `Premchand C. Suthar` can still reach
	`PREMCHAND CHANANARAM SUTHAR` — the abbreviated middle name is noise, not
	a distinguishing feature.
	"""
	return {t for t in normalize_name(value).split() if len(t) > 1}


def token_similarity(a_tokens, b_tokens):
	"""Order-independent F1 over name tokens, 0..100.

	Needed because the reader prints names in whatever order the bill uses:
	the master holds `SALIM SHAIKH` and the bill says `SHAIKH SALIM`. Edit
	distance on the whole string scores that poorly; a token set scores it 100.
	It also correctly keeps `SHAIKH SHAHRUKH` well apart from `SHAIKH SALIM`,
	which shares only one of two tokens.
	"""
	if not a_tokens or not b_tokens:
		return 0.0
	overlap = a_tokens & b_tokens
	if not overlap:
		return 0.0
	precision = len(overlap) / len(b_tokens)
	recall = len(overlap) / len(a_tokens)
	return 100.0 * 2 * precision * recall / (precision + recall)


def levenshtein(a, b):
	if a == b:
		return 0
	if not a:
		return len(b)
	if not b:
		return len(a)
	prev = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		curr = [i]
		for j, cb in enumerate(b, 1):
			curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
		prev = curr
	return prev[-1]


def similarity(a, b):
	"""0..100."""
	longest = max(len(a), len(b))
	if longest == 0:
		return 100.0
	return (1 - levenshtein(a, b) / longest) * 100.0


def match_supplier(vendor_name, vendor_gstin=None):
	"""Resolve the seller to a Supplier.

	Order: tax_id exact -> name exact -> fuzzy. India Compliance is not
	installed, so there is no `gstin` field on Supplier — `tax_id` is the only
	place a GSTIN could be, and it is usually empty. Name matching does the real
	work here.

	Returns {supplier, supplier_name, confidence, method, candidates[]}.
	"""
	result = {"supplier": None, "supplier_name": None, "confidence": 0.0, "method": None, "candidates": []}
	if not vendor_name:
		return result

	if vendor_gstin:
		hit = frappe.db.get_value(
			"Supplier", {"tax_id": vendor_gstin}, ["name", "supplier_name"], as_dict=True
		)
		if hit:
			return {
				"supplier": hit.name,
				"supplier_name": hit.supplier_name,
				"confidence": 100.0,
				"method": "tax_id",
				"candidates": [],
			}

	suppliers = frappe.get_all("Supplier", fields=["name", "supplier_name"], limit_page_length=0)
	target = normalize_name(vendor_name)
	target_tokens = name_tokens(vendor_name)
	if not target:
		return result

	scored = []
	for s in suppliers:
		label = s.supplier_name or s.name
		norm = normalize_name(label)
		if not norm:
			continue
		if norm == target:
			return {
				"supplier": s.name,
				"supplier_name": label,
				"confidence": 100.0,
				"method": "exact_name",
				"candidates": [],
			}
		# Best of the two views: character-level for typos and misreads,
		# token-level for reordered names and abbreviated initials.
		score = max(
			similarity(target, norm),
			token_similarity(target_tokens, name_tokens(label)),
		)
		scored.append((score, s.name, label))

	scored.sort(reverse=True)
	top = scored[:5]
	result["candidates"] = [
		{"supplier": name, "supplier_name": label, "score": round(score, 1)}
		for score, name, label in top
		if score >= FUZZY_SUGGEST
	]
	if top and top[0][0] >= FUZZY_ACCEPT:
		score, name, label = top[0]
		result.update({
			"supplier": name,
			"supplier_name": label,
			"confidence": round(score, 1),
			"method": "fuzzy_name",
		})
	return result


def suggest_item_group(supplier):
	"""The item group this supplier's receipts usually carry.

	A SUGGESTION only — `custom_item_group` is what PR Workflow 3 routes
	approvals on, so it is never applied without the user confirming it.
	"""
	if not supplier:
		return None

	rows = frappe.db.sql(
		"""
		SELECT custom_item_group AS grp, COUNT(*) AS n
		FROM `tabPurchase Receipt`
		WHERE supplier = %s
		  AND custom_item_group IS NOT NULL AND custom_item_group != ''
		GROUP BY custom_item_group
		ORDER BY n DESC
		LIMIT 2
		""",
		supplier,
		as_dict=True,
	)
	if not rows:
		return None

	total = sum(r.n for r in rows)
	best = rows[0]
	return {
		"item_group": best.grp,
		"seen": best.n,
		# Share of this supplier's recent receipts using it — shown to the user so a
		# supplier who genuinely varies doesn't get a confident-looking wrong answer.
		"share": round(100.0 * best.n / total, 0) if total else 0,
	}


# Tokens that carry no distinguishing meaning on a bill line.
_STOP_TOKENS = {
	"the", "and", "of", "for", "with", "size", "qty", "no", "nos", "pcs", "pc",
	"set", "type", "new", "old", "per", "each",
}


def tokens(value):
	"""Word tokens, minus noise. Kept alphanumeric so '100gsm', 'a4' survive.

	Single-character tokens are dropped EXCEPT digits. That exception matters:
	dropping the "5" from "GRADE-5" made "Grade 4", "Grade 5" and "Grade 6"
	score identically, so the shortlist offered three indistinguishable options
	for a line that names its grade explicitly.
	"""
	if not value:
		return set()
	raw = re.split(r"[^\w]+", str(value).lower())
	return {
		t for t in raw
		if t and t not in _STOP_TOKENS and (len(t) > 1 or t.isdigit())
	}


def token_score(line_tokens, item_tokens):
	"""Similarity of a short item name to a long bill line, 0..100.

	Edit distance is the wrong tool here. A bill line reads
	"GRADE-5-PAREN UNDERTAKING-PARENT COPY QTY.12(8.5x12-40PAGES) PPR100BOND..."
	while the item is called "Grade 5 undertaking_ parent copy" — Levenshtein
	scores that near zero purely on the length gap, which is why the first
	version of this matched nothing at all.

	So: token overlap, scored F1-style. Precision alone (how much of the item
	name appears in the line) over-rewards very short names — "Marker Board"
	scores 100% against "BOARD MARKER BLUE" because both its words appear, even
	though the right answer is "White Board Marker Blue Camlin". Balancing it
	against recall (how much of the line the item explains) pulls those down.
	"""
	if not item_tokens or not line_tokens:
		return 0.0
	overlap = line_tokens & item_tokens
	# One shared word is coincidence ("copy", "paper"). Demand two, unless the
	# item name is a single word to begin with.
	if len(overlap) < 2 and len(item_tokens) > 1:
		return 0.0
	precision = len(overlap) / len(item_tokens)
	recall = len(overlap) / len(line_tokens)
	if precision + recall == 0:
		return 0.0
	return 100.0 * 2 * precision * recall / (precision + recall)


ITEM_SUGGEST = 30.0


def match_items(lines, supplier=None):
	"""Match each bill line to an Item.

	Two-pass, mirroring what made the item-group suggestion work: look at what
	this supplier has actually been billed for before, then fall back to the full
	master. A supplier's own history is a far smaller and far more relevant
	candidate set than 6,141 items.

	**Never picks an item on its own**, deliberately. Measured against real bill
	lines, the top candidate is wrong often enough to rule auto-fill out:

	  * "GRADE-5-PAREN UNDERTAKING" ties Grade 4 / Grade 5 / Grade 6 at the same
	    score — a tie-break would have silently chosen Grade 4.
	  * "BOARD MARKER BLUE" ranks "Marker Board" (a whiteboard) top, while the
	    right answer "White Board Marker Blue Camlin" sits lower.

	The correct item is almost always somewhere in the shortlist, so the user
	picks from four candidates instead of searching 6,141 items. A wrong item
	corrupts stock silently; an empty item field simply cannot be saved, so a
	mistake here stays loud.
	"""
	if not lines:
		return []

	prior = set()
	if supplier:
		prior = {
			r.item_code
			for r in frappe.db.sql(
				"""
				SELECT DISTINCT pri.item_code
				FROM `tabPurchase Receipt Item` pri
				JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
				WHERE pr.supplier = %s AND pri.item_code IS NOT NULL
				""",
				supplier,
				as_dict=True,
			)
		}

	items = frappe.get_all(
		"Item",
		fields=["name", "item_name", "item_group", "stock_uom"],
		filters={"disabled": 0},
		limit_page_length=0,
	)
	index = [(tokens(i.item_name or i.name), i) for i in items]

	out = []
	for line in lines:
		line_tokens = tokens(line.get("description"))
		scored = []
		for item_tokens, item in index:
			score = token_score(line_tokens, item_tokens)
			if score <= 0:
				continue
			# Prefer what this supplier has actually billed before.
			if item.name in prior:
				score = min(100.0, score + 12.0)
			scored.append((score, item))

		scored.sort(key=lambda t: (-t[0], t[1].name))
		candidates = [
			{
				"item_code": i.name,
				"item_name": i.item_name,
				"item_group": i.item_group,
				"stock_uom": i.stock_uom,
				"score": round(s, 1),
				"seen_before": i.name in prior,
			}
			for s, i in scored[:4]
			if s >= ITEM_SUGGEST
		]

		out.append({
			"description": line.get("description"),
			"quantity": line.get("quantity"),
			"rate": line.get("rate"),
			"amount": line.get("lineAmount"),
			"uom": line.get("unit"),
			# Always None — see the docstring. The user chooses from `candidates`.
			"item_code": None,
			"candidates": candidates,
		})
	return out
