# Blinded peer-review form

Second-rater scoring for the **150/150** live run (`outputs/20260819T010032Z-477c3a3e/` — Q1–Q30 × 5 models). Same 7 rubric dimensions and accept/reject/refine fields as `judgement_log/`.

Q11–Q30 are still `"status": "draft"` until Jack signs them off; this form scores the AI text from that run, it does not promote those cases.

This is not a hosted Google Form (150 items × scores + reasoning would be unusable there, and the project stays local). The HTML file *looks* like a Google Form: **one student question per page with all 5 AI replies (A–E) under it**, a progress bar, and autosave in the browser.

How the rater scores (designed for speed):

- Scores are 1–5 click-pills per rubric row; hovering a row name shows its anchors, and a hint shows the anchor text for the chosen score. After any click, focus moves to the next row, so a rater can type `4 5 3 4 5 4 5` on the keyboard for a whole reply.
- `judgement` is pre-set to **accept** (PROCESS.md step 5 defines accept as the default); the rater switches to reject/refine only when needed. `refine` reveals the required detail box.
- **Next never blocks.** Incomplete replies are listed on the Review & submit page with jump links; import skips anything still incomplete.
- The final page offers **Download answers (.json)** and **Copy answers as text** (for phones where downloads are awkward — they can paste the JSON into the chat and you save it to a file).
- Progress from the earlier one-reply-per-page form is migrated automatically (same `pack_id`).

**Send your friend only** `peer_review/generated/SIT724_peer_review.html`. Do not send the repo, `outputs/`, or `blind_map.json` — those unblind the models.

## Build the file to email

```bash
python pipeline/peer_review.py --build
```

Then email / message `peer_review/generated/SIT724_peer_review.html` (one self-contained file, ~180 KB, works offline). Your friend opens it in a browser (Chrome/Safari/Firefox), works through 30 question pages (several hours; they can pause), clicks **Download answers** or **Copy answers as text**, and sends the JSON back.

Keep `peer_review/generated/blind_map.json` on your machine. It maps each blinded item ID back to the model so import can write a valid judgement-log row.

## Import their answers

```bash
python pipeline/peer_review.py --import ~/Downloads/sit724-peer-alex-complete.json
```

Or use the GUI **Peer review** tab → Import. That appends to `judgement_log/entries.json` and runs the existing schema validator.

## Same-laptop / same-Wi-Fi

```bash
streamlit run app.py
```

Open the **Peer review** tab. For a friend on your Wi-Fi:

```bash
streamlit run app.py --server.address 0.0.0.0
```

and send them the Network URL Streamlit prints. That tab still hides model names.

## Design (for Jack)

- Rater is blind to `model` (PROCESS.md). Cases are grouped (5 AI replies for the same student question in a row, model order shuffled) so a repeated question is obviously intentional.
- Returned JSON has no model names. Unblinding happens only at import, locally.
- Do not invent scores. Empty / partial downloads are skipped on import until judgement + reasoning are present.
