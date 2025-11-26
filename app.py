import os
from pathlib import Path
import json
import time
import csv
from datetime import datetime
import requests
import streamlit as st
import pandas as pd

# ----------------------------
# CONFIG / CONSTANTS
# ----------------------------
PRICE_POINTS = [
    200000, 250000, 300000, 350000, 400000, 450000, 500000, 550000, 600000,
    700000, 750000, 800000, 850000, 900000, 950000, 1000000, 1100000, 1200000,
    1300000, 1400000, 1500000, 1600000, 1700000, 1800000, 1900000, 2000000,
    2250000, 2500000, 2750000, 3000000, 3500000, 4000000, 4500000, 5000000,
    6000000, 7000000, 8000000, 9000000, 10000000
]

SUBURBS = {
    "Caringbah": 5710753,
    "Caringbah South": 6215183,
    "Dolans Bay": 5710812,
    "Taren Point": 5711145,
    "Cronulla": 5710793,
    "Port Hacking": 6217567,
}


# ----------------------------
# CORE LOGIC
# ----------------------------
def check_property_in_price_range(
    target_address: str,
    min_price: int,
    max_price: int,
    suburb_id: int,
    max_results: int = 500,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    carspaces: int | None = None,
) -> bool:
    """
    Check if a property appears in search results for a given price range.
    Returns True if found, False otherwise.
    """
    url = "https://bff.homely.com.au/graphql"
    headers = {
        "accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.homely.com.au",
        "priority": "u=1, i",
    }
    target_normalized = target_address.lower().strip()
    results_per_page = 25
    pages_to_check = (max_results + results_per_page - 1) // results_per_page

    for page in range(pages_to_check):
        skip = page * results_per_page
        search_params = {
            "price": {
                "__typename": "MinAndMaxFilter",
                "min": min_price,
                "max": max_price,
            },
            "bathrooms": bathrooms,
            "bedrooms": bedrooms,
            "carSpaces": carspaces,
            "propertyFeatures": [],
            "propertyTypes": [],
            "inspection": None,
            "auction": None,
            "frontageSize": None,
            "landSize": None,
            "isUnderOffer": None,
            "locationSearchContext": {
                "__typename": "SuburbsSearch",
                "searchLocations": [{"id": suburb_id}],
                "includeSurroundingSuburbs": True,
            },
            "paging": {"skip": skip, "take": results_per_page},
            "context": "location",
            "searchMode": "sold",
            "sortBy": "soldHomesForYou",
            "__typename": "SearchParams",
        }
        query_str = "searchParamsJSON=" + json.dumps(
            search_params, separators=(",", ":")
        )
        payload = {
            "operationName": "listingMapMarkerSearch",
            "variables": {"query": query_str},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "f51020d6110a7a6730645cb8bcdd2a344462684c344b8d88836d7588d3bc39b8",
                }
            },
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    time.sleep(1)
                    continue

                listings = None
                data = response_data.get("data", {})
                if "listingSearch" in data:
                    listings = data["listingSearch"].get("listings", [])
                elif "listingMapMarkerSearch" in data:
                    listings = data["listingMapMarkerSearch"].get("results", [])

                if not listings:
                    break

                for listing in listings:
                    address_text = None
                    if "location" in listing and "address" in listing["location"]:
                        address_text = listing["location"]["address"]
                    elif "address" in listing:
                        if isinstance(listing["address"], dict):
                            address_text = listing["address"].get("display", "")
                        else:
                            address_text = listing["address"]

                    if address_text:
                        address_normalized = address_text.lower().strip()
                        if target_normalized in address_normalized:
                            return True

                if page < pages_to_check - 1:
                    time.sleep(0.2)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(1)
            continue
        except Exception:
            time.sleep(1)
            continue
    return False


def refine_to_10k_window(
    target_address: str,
    suburb_id: int,
    suburb_name: str,
    min_price: int,
    max_price: int,
    max_results: int = 500,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    carspaces: int | None = None,
) -> dict:
    """
    Refine a price bracket down to a ~10K window using binary splitting on raw prices.
    Returns dict with min_price, max_price, bracket_width, queries_made.
    """
    queries_made = 0
    lo = min_price
    hi = max_price

    while hi - lo > 10000:
        mid = (lo + hi) // 2
        found = check_property_in_price_range(
            target_address,
            lo,
            mid,
            suburb_id,
            max_results=max_results,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            carspaces=carspaces,
        )
        queries_made += 1
        if found:
            hi = mid
        else:
            lo = mid + 1

    centre = (lo + hi) // 2
    low_band = (centre // 10000) * 10000
    high_band = low_band + 10000

    return {
        "min_price": low_band,
        "max_price": high_band,
        "bracket_width": high_band - low_band,
        "queries_made": queries_made,
    }


def binary_search_price_range(
    target_address: str,
    suburb_id: int,
    suburb_name: str,
    price_points=PRICE_POINTS,
    max_results: int = 500,
    find_exact: bool = False,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    carspaces: int | None = None,
) -> dict:
    """
    Use binary search over predefined price points to find a price bracket,
    optionally refined to a 10K window.
    """
    min_possible = price_points[0]
    max_possible = price_points[-1]
    queries_made = 0

    # Step 1: Verify existence
    exists = check_property_in_price_range(
        target_address,
        min_possible,
        max_possible,
        suburb_id,
        max_results=max_results,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        carspaces=carspaces,
    )
    queries_made += 1

    if not exists:
        return {
            "found": False,
            "message": "Property not found in database or address/filters are incorrect",
            "suburb": suburb_name,
            "address": target_address,
        }

    # Step 2: Lower bound
    lo = 0
    hi = len(price_points) - 1
    lower_bound_index = 0

    while lo <= hi:
        mid = (lo + hi) // 2
        threshold = price_points[mid]
        found = check_property_in_price_range(
            target_address,
            threshold,
            max_possible,
            suburb_id,
            max_results=max_results,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            carspaces=carspaces,
        )
        queries_made += 1
        if found:
            lower_bound_index = mid
            lo = mid + 1
        else:
            hi = mid - 1
    lower_bound = price_points[lower_bound_index]

    # Step 3: Upper bound
    lo = 0
    hi = len(price_points) - 1
    upper_bound_index = len(price_points) - 1

    while lo <= hi:
        mid = (lo + hi) // 2
        threshold = price_points[mid]
        found = check_property_in_price_range(
            target_address,
            min_possible,
            threshold,
            suburb_id,
            max_results=max_results,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            carspaces=carspaces,
        )
        queries_made += 1
        if found:
            upper_bound_index = mid
            hi = mid - 1
        else:
            lo = mid + 1
    upper_bound = price_points[upper_bound_index]

    final_min = lower_bound
    final_max = upper_bound

    # Optional 10K refinement
    if find_exact and (final_max - final_min) > 10000:
        refine_result = refine_to_10k_window(
            target_address,
            suburb_id,
            suburb_name,
            final_min,
            final_max,
            max_results=max_results,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            carspaces=carspaces,
        )
        total_queries = queries_made + refine_result["queries_made"]
        return {
            "found": True,
            "exact": True,
            "price": None,
            "min_price": refine_result["min_price"],
            "max_price": refine_result["max_price"],
            "bracket_width": refine_result["bracket_width"],
            "queries_made": total_queries,
            "address": target_address,
            "suburb": suburb_name,
        }

    # Coarse bracket only
    return {
        "found": True,
        "exact": False,
        "price": None,
        "min_price": final_min,
        "max_price": final_max,
        "bracket_width": final_max - final_min,
        "queries_made": queries_made,
        "address": target_address,
        "suburb": suburb_name,
    }


# ----------------------------
# CSV HELPERS
# ----------------------------
def find_csv_anywhere(filename: str) -> str | None:
    """
    Allow user to type only the CSV filename (if using manual path).
    In Streamlit we mostly use uploaded files, but this is kept for flexibility.
    """
    filename = filename.strip()
    if os.path.isabs(filename):
        return filename if os.path.exists(filename) else None

    home = Path.home()
    search_paths = [
        Path.cwd() / filename,
        home / "Downloads" / filename,
        home / "Desktop" / filename,
        home / "Documents" / filename,
    ]

    for path in search_paths:
        if path.exists():
            return str(path)
    return None


def parse_uploaded_csv(file) -> list[dict]:
    """
    Parse an uploaded CSV (streamlit file-like object).
    STRICT header: address,bedrooms,bathrooms,carspaces
    Returns list of dicts with keys: address (str), bedrooms (int|None), bathrooms (int|None), carspaces (int|None)
    """
    expected_headers = ["address", "bedrooms", "bathrooms", "carspaces"]
    rows: list[dict] = []
    try:
        file.seek(0)
        text = file.read().decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        fieldnames = reader.fieldnames
        if fieldnames is None:
            st.error("CSV appears to have no header row.")
            return []
        if fieldnames != expected_headers:
            st.error(
                "CSV header must be exactly:\n"
                "address,bedrooms,bathrooms,carspaces\n"
                f"Found: {', '.join(fieldnames)}"
            )
            return []

        for idx, row in enumerate(reader, start=2):
            address = (row.get("address") or "").strip()
            if not address:
                st.warning(f"Line {idx}: empty address, row skipped.")
                continue

            def parse_int_field(key: str) -> int | None:
                val = (row.get(key) or "").strip()
                if val == "":
                    return None
                try:
                    return int(val)
                except ValueError:
                    st.warning(
                        f"Line {idx}: invalid integer for '{key}' -> '{val}', "
                        "treated as 'any'."
                    )
                    return None

            bedrooms = parse_int_field("bedrooms")
            bathrooms = parse_int_field("bathrooms")
            carspaces = parse_int_field("carspaces")

            rows.append(
                {
                    "address": address,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "carspaces": carspaces,
                }
            )
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        return []
    return rows


# ----------------------------
# STREAMLIT UI
# ----------------------------
def main():
    st.set_page_config(
        page_title="Homely Hidden Price Discovery",
        page_icon="💰",
        layout="wide",
    )
    st.title("💰 Homely Hidden Price Discovery Tool")
    st.write(
        "Discover hidden **sold prices** for properties with undisclosed prices, "
        "using binary search across Homely sold listings."
    )

    # Sidebar: suburb + options
    st.sidebar.header("Search Settings")
    suburb_name = st.sidebar.selectbox(
        "Suburb", options=list(SUBURBS.keys()), index=4  # default Cronulla
    )
    suburb_id = SUBURBS[suburb_name]
    st.sidebar.write(f"**Selected Suburb ID:** `{suburb_id}`")

    refine_to_10k = st.sidebar.checkbox(
        "Refine to 10K price window",
        value=True,
        help="If enabled, the tool will narrow the price to a ~$10,000 window.",
    )

    max_results = st.sidebar.slider(
        "Max results per search (affects depth)",
        min_value=100,
        max_value=1000,
        step=100,
        value=500,
        help="Maximum number of results to scan per query.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Mode**")
    mode = st.sidebar.radio(
        "Select mode:",
        options=["Single Property", "Batch via CSV"],
        index=0,
    )

    if mode == "Single Property":
        run_single_property_mode(suburb_name, suburb_id, refine_to_10k, max_results)
    else:
        run_batch_csv_mode(suburb_name, suburb_id, refine_to_10k, max_results)


def run_single_property_mode(
    suburb_name: str, suburb_id: int, refine_to_10k: bool, max_results: int,
):
    st.subheader("🏠 Single Property Search")
    col1, col2 = st.columns([2, 1])

    with col1:
        address = st.text_input(
            "Property address",
            placeholder="e.g. G01/79 Gerrale Street, Cronulla NSW 2230",
        )

    with col2:
        st.markdown("**Optional filters**")
        bedrooms = st.number_input(
            "Bedrooms", min_value=0, step=1, value=0, help="0 means 'any'."
        )
        bathrooms = st.number_input(
            "Bathrooms", min_value=0, step=1, value=0, help="0 means 'any'."
        )
        carspaces = st.number_input(
            "Car spaces", min_value=0, step=1, value=0, help="0 means 'any'."
        )

    # Convert 0 → None (no filter)
    bedrooms_filter = bedrooms or None
    bathrooms_filter = bathrooms or None
    carspaces_filter = carspaces or None

    run_button = st.button("🔍 Run Search")

    if run_button:
        if not address.strip():
            st.error("Please enter a property address.")
            return

        with st.spinner("Searching for hidden price range..."):
            result = binary_search_price_range(
                target_address=address.strip(),
                suburb_id=suburb_id,
                suburb_name=suburb_name,
                max_results=max_results,
                find_exact=refine_to_10k,
                bedrooms=bedrooms_filter,
                bathrooms=bathrooms_filter,
                carspaces=carspaces_filter,
            )

        if not result.get("found"):
            st.error(
                "Property not found with the given address/filters. "
                "Try loosening filters or checking the address."
            )
            return

        if result.get("exact"):
            st.success(
                f"10K PRICE WINDOW: "
                f"${result['min_price']:,} - ${result['max_price']:,}"
            )
        else:
            st.success(
                f"Discovered price bracket: "
                f"${result['min_price']:,} - ${result['max_price']:,}"
            )

        st.write(
            f"**Suburb:** {suburb_name} | "
            f"**Bracket width:** ${result['bracket_width']:,} | "
            f"**API queries:** {result['queries_made']}"
        )


def run_batch_csv_mode(
    suburb_name: str, suburb_id: int, refine_to_10k: bool, max_results: int,
):
    st.subheader("📂 Batch Search via CSV")
    st.markdown(
        """
        Upload a CSV file with **exactly** these columns:
        ```csv
        address,bedrooms,bathrooms,carspaces
        G01/79 Gerrale Street, Cronulla NSW 2230,3,3,2
        12 Smith St, Caringbah NSW 2229,3,2,1
        ...
        address is required
        bedrooms, bathrooms, carspaces may be blank → treated as "any"
        """
    )

    uploaded_file = st.file_uploader(
        "Upload CSV file", type=["csv"], accept_multiple_files=False
    )

    if not uploaded_file:
        st.info("Upload a CSV file to begin.")
        return

    rows = parse_uploaded_csv(uploaded_file)
    if not rows:
        return

    st.success(f"Loaded {len(rows)} properties from CSV.")
    st.dataframe(
        pd.DataFrame(rows).head(10),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Showing first 10 rows.")

    run_batch = st.button("🚀 Run Batch Search")
    if not run_batch:
        return

    results = []
    total = len(rows)
    progress_bar = st.progress(0)
    status_placeholder = st.empty()

    with st.spinner("Processing properties..."):
        for idx, row in enumerate(rows, start=1):
            address = row["address"]
            bedrooms = row["bedrooms"]
            bathrooms = row["bathrooms"]
            carspaces = row["carspaces"]

            status_placeholder.text(
                f"Processing {idx}/{total}: {address} "
                f"(Beds: {bedrooms or 'any'}, Baths: {bathrooms or 'any'}, "
                f"Cars: {carspaces or 'any'})"
            )

            result = binary_search_price_range(
                target_address=address,
                suburb_id=suburb_id,
                suburb_name=suburb_name,
                max_results=max_results,
                find_exact=refine_to_10k,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                carspaces=carspaces,
            )

            if not result.get("found"):
                result_row = {
                    "Address": address,
                    "Suburb": suburb_name,
                    "Found": False,
                    "TenKWindowMode": refine_to_10k,
                    "Price": "",
                    "Min Price": "",
                    "Max Price": "",
                    "Bracket Width": "",
                    "Queries Made": result.get("queries_made", ""),
                    "Error": result.get("message", "Not found"),
                }
            else:
                result_row = {
                    "Address": address,
                    "Suburb": suburb_name,
                    "Found": True,
                    "TenKWindowMode": result.get("exact", False),
                    "Price": result.get("price", ""),
                    "Min Price": result.get("min_price", ""),
                    "Max Price": result.get("max_price", ""),
                    "Bracket Width": result.get("bracket_width", ""),
                    "Queries Made": result.get("queries_made", ""),
                    "Error": "",
                }
            results.append(result_row)
            progress_bar.progress(int(idx * 100 / total))
            # polite delay to avoid hammering the API
            time.sleep(0.3)

    status_placeholder.text("Batch processing complete.")
    df_results = pd.DataFrame(results)

    st.subheader("📊 Results Summary")
    st.dataframe(df_results, use_container_width=True)

    # Download button
    csv_buffer = df_results.to_csv(index=False).encode("utf-8")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"price_discovery_{suburb_name.replace(' ', '')}{timestamp}.csv"

    st.download_button(
        label="💾 Download results as CSV",
        data=csv_buffer,
        file_name=filename,
        mime="text/csv",
    )
    st.success("Batch complete. You can now download the results.")


if name == "main":
    main()
