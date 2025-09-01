# NC House — Firefighter Legislation Dashboard (Streamlit)

This is a **ready-to-deploy Streamlit app** that builds a **live**, drill‑down dashboard of all **North Carolina House** members, their party (with 🫏/🐘 icons), contact information, and their votes — with a focus on identifying **firefighter‑related legislation** based on the **Keywords** listed on each bill page.

## Features
- **Live scrape** from the official NCGA website (no third‑party API keys).
- House member directory with **party, district, counties, phone, assistant, email**, and quick links.
- Per‑member **vote history** with a computed view of **support/oppose** on firefighter‑related bills.
- Build a **roll‑call matrix** of Aye/No across **all members** for firefighter bills.
- **Keyword list** is configurable (defaults include: *FIREFIGHTERS & FIREFIGHTING, EMS, RESCUE SQUADS, FIREMENS PENSION FUND,* etc.).
- Caches results to keep it snappy; **Refresh** button re-fetches everything.

## One‑click deploy (Streamlit Community Cloud)
1. Create a free account at https://streamlit.io/cloud and click **New app**.
2. Push this folder to a new GitHub repo, select it in Streamlit Cloud, and set:
   - **Main file:** `app.py`
   - **Python version:** 3.11+
3. Click **Deploy**. Share your public URL with members.

> Tip: You can also run locally with `pip install -r requirements.txt` then `streamlit run app.py`.

## How it classifies “firefighter‑related”
For each bill a member voted on, the app opens the bill page (e.g., `https://www.ncleg.gov/BillLookup/2025/H37`) and reads the **Keywords** section. If it contains any of your configured keywords (default includes **FIREFIGHTERS & FIREFIGHTING**), it treats the bill as firefighter‑related. We also do a light heuristic on the bill title for words like “firefighter”, “EMS”, “rescue”, “9‑1‑1”, or “pension”.

- **Support** = the member voted **Aye** on a vote whose **result was PASS** and where the **motion** is one you chose to count (defaults: 2nd/3rd Reading, Concur, For Adoption).
- **Oppose** = the member voted **No** on such a vote.
- Everything else is shown as **not counted** (e.g., procedures you’ve opted to ignore or failed votes).

## Data sources (official NCGA)
- House member list with party, counties, phone, assistants:  
  `https://www.ncleg.gov/Members/MemberList/H`
- House contact emails and phones:  
  `https://www.ncleg.gov/Members/ContactInfo/H`
- Per‑member vote histories (example):  
  `https://www.ncleg.gov/Members/Votes/H/725`
- Bill pages with Keywords (example — HB 37, “Enhance Firefighter Benefits & Representation.”):  
  `https://www.ncleg.gov/BillLookup/2025/H37`

## Notes & guardrails
- The NCGA website sometimes changes layout; the scraper aims to be robust but may need tweaks over time.
- To be considerate of NCGA servers, the app caches results for 6 hours by default.
- For Senate, you can extend this by duplicating the functions and swapping `/H/` for `/S/`.
- Want 24/7 reliability and faster loads? You can add a tiny backend cache (e.g., Cloud Run or a nightly GitHub Action to prebuild CSVs).

---

*Built for IAFF Local 673.*