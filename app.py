
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from functools import lru_cache
import re
from datetime import datetime, timedelta

BASE = "https://www.ncleg.gov"
SESSION = "2025"  # adjust if needed for future sessions
HOUSE_MEMBER_LIST = f"{BASE}/Members/MemberList/H"
HOUSE_CONTACTS = f"{BASE}/Members/ContactInfo/H"

HEADERS = {
    "User-Agent": "Local673-Firefighter-Dashboard/1.0 (+https://www.local673.org)"
}

st.set_page_config(page_title="NC House — Firefighter Legislation Dashboard",
                   page_icon="🚒",
                   layout="wide")

st.title("🚒 NC House — Firefighter Legislation Dashboard")
st.caption("Live scraper of the NC General Assembly site (House). Built for IAFF Local 673 members.")

with st.expander("How this works / Notes", expanded=False):
    st.markdown("""
- **Live data:** This app scrapes the official NCGA site in real time. Use the **Refresh** button any time.
- **Firefighter-related bills:** We flag bills whose **Keywords** on the bill page include things like **FIREFIGHTERS & FIREFIGHTING**, **EMERGENCY MEDICAL SERVICES**, **RESCUE SQUADS**, **FIREMENS PENSION FUND**, etc. You can add/remove keywords below.
- **Vote classification:** For each flagged bill, we mark **Aye on PASS** as _supports_ and **No on PASS** as _opposes_. You can choose whether to include procedural reads (2nd/3rd Reading) and concur motions.
- **Performance tip:** Loading all vote histories can take a minute. You can toggle between _lazy_ and _preload_ modes.
""")

# ---------- Utilities ----------

@lru_cache(maxsize=1)
def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def parse_house_member_list():
    html = fetch_html(HOUSE_MEMBER_LIST)
    soup = BeautifulSoup(html, "lxml")

    cards = []
    # Member cards are grouped; find all anchor names + party markers
    # Each member block starts with an <a> around the name, followed by party (R)/(D)
    # We'll find all anchors that link to /Members/Biography/H/{id}
    for a in soup.select('a[href*="/Members/Biography/H/"]'):
        name = a.get_text(strip=True)
        href = urljoin(BASE, a.get("href"))
        # Back up to the parent container to extract party, district, county, phone, assistant
        container = a.find_parent()
        block_text = container.get_text("\n", strip=True) if container else ""

        # Member ID
        m = re.search(r"/H/(\d+)", href)
        member_id = m.group(1) if m else None

        # Try to find party marker on same line as name like "(R)" or "(D)"
        # We'll scan next siblings too
        party = None
        # Look ahead for the following text nodes:
        siblings_text = ""
        for sib in container.contents if container else []:
            try:
                siblings_text += (sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib)).strip() + " "
            except Exception:
                pass
        mparty = re.search(r"\((R|D|Unaffiliated|Independent)\)", siblings_text)
        if mparty:
            party = mparty.group(1)
        if party in ("Unaffiliated","Independent"):
            party = "U"

        # District: look for "District NN"
        mdist = re.search(r"District\s+(\d+)", siblings_text)
        district = mdist.group(1) if mdist else ""

        # Counties: they're shown as county names on distinct lines
        # We'll try to grab all following <a> county links within same container
        counties = [x.get_text(strip=True) for x in container.select('a[href*="/Counties/"]')]

        # Phone
        mphone = re.search(r"Phone:\s*([\d\-\(\)\s]+)", siblings_text)
        phone = mphone.group(1).strip() if mphone else ""

        # Assistant:
        massist = re.search(r"Assistant:\s*(.+)$", siblings_text)
        assistant = massist.group(1).strip() if massist else ""

        cards.append({
            "name": name,
            "member_id": member_id,
            "party": party or "",
            "district": district,
            "counties": ", ".join(counties),
            "office_phone": phone,
            "assistant": assistant,
            "bio_url": href,
            "votes_url": f"{BASE}/Members/Votes/H/{member_id}" if member_id else ""
        })
    df = pd.DataFrame(cards).drop_duplicates(subset=["member_id"]).reset_index(drop=True)
    return df

def parse_house_contacts():
    html = fetch_html(HOUSE_CONTACTS)
    soup = BeautifulSoup(html, "lxml")
    rows = []
    # The page is a table-like list; each row has 'Member', 'Phone', 'Email'
    # Grab all email anchors and walk up to get the member name
    for email_a in soup.select('a[href^="mailto:"]'):
        email = email_a.get_text(strip=True)
        row = email_a.find_parent("tr")
        if not row:
            # fallback: find previous link (member)
            mem_a = soup.select_one("a[href*='/Members/Biography/H/']")
            continue
        tds = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if len(tds) >= 1:
            member_text = row.find("a")
            member_name = member_text.get_text(strip=True) if member_text else tds[0]
        else:
            member_name = ""
        phone = ""
        # Attempt to find phone in this row
        for td in row.find_all("td"):
            m = re.search(r"\(?\d{3}\)?[-\s]\d{3}[-]\d{4}", td.get_text(" ", strip=True))
            if m:
                phone = m.group(0)
                break
        rows.append({"name": member_name.replace("Rep. ","").strip(), "email": email, "contact_phone": phone})
    # Also parse by scanning lines as backup
    dfc = pd.DataFrame(rows).drop_duplicates(subset=["name"])
    return dfc

@lru_cache(maxsize=512)
def fetch_bill_keywords(bill_url: str):
    """Return a set of Keywords from the bill page."""
    try:
        html = fetch_html(bill_url)
    except Exception as e:
        return set()
    soup = BeautifulSoup(html, "lxml")
    # The Keywords line appears under "Attributes:" on the bill page
    text = soup.get_text("\n", strip=True)
    # Look for "Keywords:" then read until newline
    kw = set()
    m = re.search(r"Keywords:\s*(.+?)\n", text)
    if m:
        # Keywords are separated by semicolons
        raw = m.group(1)
        for part in raw.split(";"):
            kw.add(part.strip().upper())
    return kw

def parse_member_votes(member_id: str):
    """Parse the vote history table from a member's 'Votes' page."""
    url = f"{BASE}/Members/Votes/H/{member_id}"
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    # vote table rows have columns: RCS#, Doc, Subject/Motion, Date, Vote, Aye, No, ...
    # We'll collect RCS, bill code and link, subject, date, vote, result
    vote_rows = []
    # Find all rows that contain a Doc link to bill lookup or bill id
    for tr in soup.select("tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        # Find doc link in row
        doc_a = tr.find("a", href=True)
        if not doc_a:
            continue
        doc_text = doc_a.get_text(strip=True)
        doc_href = urljoin(BASE, doc_a["href"])
        # We only care about bills/resolutions (HB/SB/HR/HJR etc.)
        if not re.search(r"/BillLookup/\d{4}/[HS]\d+", doc_href):
            # Try to follow redirects for 'HB ' codes
            pass
        # Extract metadata
        # Columns may be: RCS#, Doc., Subject/Motion, Date, Vote, Aye, No, Not Voting, Excused Abs., Excused Vote, Total Votes, Result
        cols = [td.get_text(" ", strip=True) for td in tds]
        # Heuristic mapping
        rcs = cols[0] if cols else ""
        subject = cols[2] if len(cols) > 2 else ""
        date = cols[3] if len(cols) > 3 else ""
        member_vote = cols[4] if len(cols) > 4 else ""
        result = cols[-1] if cols else ""

        vote_rows.append({
            "member_id": member_id,
            "rcs": rcs,
            "doc": doc_text,
            "doc_url": doc_href,
            "subject_motion": subject,
            "vote_datetime": date,
            "member_vote": member_vote,
            "result": result
        })
    return pd.DataFrame(vote_rows)

# Default firefighter-related keywords (uppercased)
DEFAULT_FF_KWS = [
    "FIREFIGHTERS & FIREFIGHTING",
    "EMERGENCY MEDICAL SERVICES",
    "RESCUE SQUADS",
    "FIREMENS PENSION FUND",
    "PENSION & RETIREMENT FUNDS",
    "9-1-1",
    "EMERGENCY SERVICES",
    "WORKERS' COMPENSATION",
    "CANCER"
]

st.sidebar.subheader("Filters & Settings")
keywords_input = st.sidebar.text_area(
    "Firefighter-related keywords (semicolon-separated, matches the bill page Keywords)",
    "; ".join(DEFAULT_FF_KWS),
    height=100
)
FF_KEYWORDS = [k.strip().upper() for k in keywords_input.split(";") if k.strip()]

include_reads = st.sidebar.multiselect(
    "Count these motions toward support/oppose",
    ["Second Reading", "Third Reading", "Concur", "Not Concur", "For Adoption"],
    default=["Second Reading", "Third Reading", "Concur", "For Adoption"]
)

mode = st.sidebar.radio("Data loading mode", ["Lazy (fast start)", "Preload all votes (thorough)"], index=0)
do_refresh = st.sidebar.button("🔄 Refresh from NCGA", type="primary")

@st.cache_data(ttl=60*60*6, show_spinner=False)
def cached_member_list():
    return parse_house_member_list()

@st.cache_data(ttl=60*60*6, show_spinner=False)
def cached_contacts():
    return parse_house_contacts()

@st.cache_data(ttl=60*60*6, show_spinner=False)
def cached_member_votes(member_id):
    return parse_member_votes(member_id)

if do_refresh:
    # Clear caches
    fetch_html.cache_clear()
    cached_member_list.clear()
    cached_contacts.clear()
    cached_member_votes.clear()
    fetch_bill_keywords.cache_clear()
    st.success("Refreshed the caches.")

members = cached_member_list()
contacts = cached_contacts()

# Merge email/alt phone from contacts
m = members.merge(contacts, how="left", on="name")

# Party icons
def party_icon(p):
    if str(p).upper().startswith("R"):
        return "🐘 R"
    if str(p).upper().startswith("D"):
        return "🫏 D"
    return str(p or "")

m["party_icon"] = m["party"].map(party_icon)

st.markdown("### House Members (click a row for drilldown)")
cols = st.columns([2,1,1,2,1,2,2])
with cols[0]:
    party_filter = st.multiselect("Party", ["D","R","U"], default=["D","R"])
with cols[1]:
    district_filter = st.text_input("District contains", "")
with cols[2]:
    county_filter = st.text_input("County contains", "")
with cols[3]:
    name_filter = st.text_input("Name contains", "")
with cols[4]:
    show_limit = st.number_input("Show first N", min_value=1, max_value=200, value=120, step=1)
with cols[5]:
    show_email = st.checkbox("Show emails", value=True)
with cols[6]:
    show_assist = st.checkbox("Show assistants", value=True)

df = m.copy()
if party_filter:
    df = df[df["party"].isin(party_filter)]
if district_filter:
    df = df[df["district"].str.contains(district_filter, case=False, na=False)]
if county_filter:
    df = df[df["counties"].str.contains(county_filter, case=False, na=False)]
if name_filter:
    df = df[df["name"].str.contains(name_filter, case=False, na=False)]

display_cols = ["name","party_icon","district","counties","office_phone"]
if show_email:
    display_cols.append("email")
if show_assist:
    display_cols.append("assistant")
display_cols += ["bio_url","votes_url"]

st.dataframe(df[display_cols].head(show_limit), use_container_width=True, hide_index=True)

st.markdown("---")

st.header("Drilldown & Firefighter Vote Map")
st.write("Select a representative below to load their vote history and see whether they supported or opposed firefighter-related bills.")

member_names = df["name"].tolist()
selected = st.selectbox("Choose a member", member_names if member_names else [""])

def compute_support_matrix(votes_df: pd.DataFrame):
    """Return (map_df, bills_df). map_df has one row with columns per bill labeled Aye/No/Other, based on firefighter-related filter."""
    if votes_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    # For each row, if doc_url points to BillLookup, fetch keywords & title
    rows = []
    bills_meta = {}
    for _, row in votes_df.iterrows():
        doc_url = row["doc_url"]
        if not doc_url:
            continue
        # Normalize to BillLookup page; if the link is not BillLookup (e.g., resolution), skip
        if "/BillLookup/" not in doc_url:
            # try to detect plain HB/SB links and transform
            pass
        # Fetch bill page only once
        if doc_url not in bills_meta:
            kws = fetch_bill_keywords(doc_url)
            title = None
            # Try fetching title (short title appears as a bold line with link text)
            try:
                html = fetch_html(doc_url)
                s = BeautifulSoup(html, "lxml")
                # short title is in an <a> element near top; grab the first <a> after the bill header
                # more robust: find the line that contains "House Bill" and the next <a>
                title_el = s.find("a", href=True, string=True)
                # But we saw a clean marker: the first strong line after header contains short title link
                # We'll fallback to document title
                title = s.title.get_text(strip=True) if s.title else ""
                # Extract short title from the page content where possible
                stxt = s.get_text("\n", strip=True)
                mtitle = re.search(r"House Bill \d+.*?\n(.*?)\n", stxt)
                if mtitle:
                    title = mtitle.group(1).strip()
            except Exception:
                title = ""
            bills_meta[doc_url] = {"keywords": kws, "short_title": title}

        meta = bills_meta[doc_url]
        # Determine if firefighter-related
        is_ff = any(k in meta["keywords"] for k in FF_KEYWORDS)
        # Also include heuristic keyword search of title
        if not is_ff and meta["short_title"]:
            if re.search(r"FIRE(FIGHT| FIGHTER|MEN)|EMS|RESCUE|9-?1-?1|PENSION", meta["short_title"], re.I):
                is_ff = True

        if not is_ff:
            continue

        # Count as support/oppose only if motion matches user selection and result is PASS
        motion = (row["subject_motion"] or "")
        consider = any(m in motion for m in include_reads)
        passed = "PASS" in (row["result"] or "").upper()

        support_flag = None
        if consider and passed:
            if row["member_vote"].strip().upper() == "AYE" or row["member_vote"].strip().upper() == "AY":
                support_flag = "Aye (supports)"
            elif row["member_vote"].strip().upper() == "NO":
                support_flag = "No (opposes)"
            else:
                support_flag = row["member_vote"]
        else:
            support_flag = f"{row['member_vote']} (not counted)"

        rows.append({
            "Bill": re.sub(r"\s+", " ", row["doc"]).strip(),
            "Short Title": meta["short_title"],
            "Motion": motion,
            "Member Vote": row["member_vote"],
            "Counted As": support_flag,
            "Result": row["result"],
            "Bill Page": row["doc_url"],
            "Keywords": "; ".join(sorted(bills_meta[doc_url]["keywords"])) if bills_meta[doc_url]["keywords"] else ""
        })

    map_df = pd.DataFrame(rows)
    # Sort to put Aye/No at top
    if not map_df.empty:
        order = {"Aye (supports)": 0, "No (opposes)": 1}
        map_df["__order"] = map_df["Counted As"].map(lambda x: order.get(x, 2))
        map_df = map_df.sort_values(["__order","Bill"]).drop(columns=["__order"])
    return map_df, pd.DataFrame.from_dict(bills_meta, orient="index").reset_index().rename(columns={"index":"Bill Page"})

if selected:
    sel_row = df[df["name"] == selected].iloc[0]
    st.subheader(f"{selected} — District {sel_row['district']} ({sel_row['party_icon']})")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"**Counties**: {sel_row['counties']}")
        st.markdown(f"**Office Phone**: {sel_row['office_phone']}")
    with c2:
        st.markdown(f"**Email**: {sel_row.get('email','')}")
        st.markdown(f"**Assistant**: {sel_row.get('assistant','')}")
    with c3:
        st.markdown(f"[Biography]({sel_row['bio_url']}) • [Votes]({sel_row['votes_url']})")

    if mode.startswith("Preload"):
        # Preload all members' votes (can be heavy)
        with st.spinner("Loading vote histories for all members..."):
            all_votes = pd.concat([cached_member_votes(mid) for mid in df["member_id"].tolist()], ignore_index=True)
        member_votes = all_votes[all_votes["member_id"] == sel_row["member_id"]].copy()
    else:
        with st.spinner("Loading this member's vote history..."):
            member_votes = cached_member_votes(sel_row["member_id"]).copy()

    if member_votes.empty:
        st.info("No votes found.")
    else:
        vote_map, bills_df = compute_support_matrix(member_votes)
        st.markdown("#### Firefighter-related votes")
        st.dataframe(vote_map, use_container_width=True, hide_index=True)
        csv = vote_map.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download these rows (CSV)", data=csv, file_name=f"{selected}_firefighter_votes.csv", mime="text/csv")

        st.markdown("#### Full vote history (raw)")
        st.dataframe(member_votes, use_container_width=True, hide_index=True)

st.markdown("---")
st.header("Find which legislators supported or opposed firefighter-related bills")

st.write("Use **Preload all votes** mode and the **Build roll‑call matrix** button to compute Aye/No across all members for just the firefighter-related bills (can take a while).")

if st.button("🧮 Build roll‑call matrix (firefighter bills only)"):
    with st.spinner("Loading vote histories and building matrix..."):
        # Load all members' votes
        all_votes = pd.concat([cached_member_votes(mid) for mid in df["member_id"].tolist()], ignore_index=True)
        # Build a set of firefighter-related bills encountered, based on keywords
        bill_pages = set()
        bill_titles = {}
        for _, row in all_votes.iterrows():
            doc = row.get("doc_url","")
            if "/BillLookup/" not in doc:
                continue
            kws = fetch_bill_keywords(doc)
            if any(k in kws for k in FF_KEYWORDS):
                bill_pages.add(doc)
                # title
                try:
                    html = fetch_html(doc)
                    s = BeautifulSoup(html, "lxml")
                    stxt = s.get_text("\n", strip=True)
                    mtitle = re.search(r"House Bill \d+.*?\n(.*?)\n", stxt) or re.search(r"Senate Bill \d+.*?\n(.*?)\n", stxt)
                    title = mtitle.group(1).strip() if mtitle else s.title.get_text(strip=True)
                except Exception:
                    title = ""
                bill_titles[doc] = title

        # Now compute, per member, their Aye/No on these bills where the motion is included and result PASS
        records = []
        for _, mem in df.iterrows():
            mv = cached_member_votes(mem["member_id"])
            for bp in bill_pages:
                rows = mv[mv["doc_url"] == bp]
                # pick rows counted by our rules
                rows = rows[rows["result"].str.contains("PASS", na=False, case=False)]
                if include_reads:
                    rows = rows[rows["subject_motion"].apply(lambda x: any(m in (x or "") for m in include_reads))]
                if rows.empty:
                    status = ""
                else:
                    # Take the last vote on that bill for this member
                    rr = rows.iloc[-1]
                    v = (rr["member_vote"] or "").strip().upper()
                    status = "Aye" if v in ("AYE","AY") else ("No" if v == "NO" else rr["member_vote"])
                records.append({
                    "Member": mem["name"],
                    "Party": mem["party"],
                    "District": mem["district"],
                    "Bill Page": bp,
                    "Bill Title": bill_titles.get(bp, ""),
                    "Vote": status
                })
        matrix = pd.DataFrame(records)
        if matrix.empty:
            st.info("No firefighter-related bills found in the current session (based on your keywords).")
        else:
            st.success(f"Matrix built for {matrix['Bill Page'].nunique()} bills across {matrix['Member'].nunique()} members.")
            st.dataframe(matrix.sort_values(["Bill Title","Party","Member"]), use_container_width=True, hide_index=True)
            st.download_button("⬇️ Download matrix (CSV)", data=matrix.to_csv(index=False).encode("utf-8"),
                               file_name="firefighter_rollcall_matrix.csv", mime="text/csv")
