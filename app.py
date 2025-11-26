import os
from pathlib import Path
import json
import time
import csv
from datetime import datetime

import requests
import streamlit as st
import pandas as pd

# -------------------------------------------------------------------
# CONFIG / CONSTANTS
# -------------------------------------------------------------------

# Predefined price points for binary search
PRICE_POINTS = [
    200000, 250000, 300000, 350000, 400000, 450000, 500000, 550000, 600000, 700000,
    750000, 800000, 850000, 900000, 950000, 1000000, 1100000, 1200000, 1300000, 1400000,
    1500000, 1600000, 1700000, 1800000, 1900000, 2000000, 2250000, 2500000, 2750000, 3000000,
    3500000, 4000000, 4500000, 5000000, 6000000, 7000000, 8000000, 9000000, 10000000
]

SUBURBS = {
    "1": {"name": "Caringbah", "id": 5710753},
    "2": {"name": "Caringbah South", "id": 6215183},
    "3": {"name": "Dolans Bay", "id": 5710812},
    "4": {"name": "Taren Point", "id": 5711145},
    "5": {"name": "Cronulla", "id": 5710793},
    "6": {"name": "Port Hacking", "id": 6217567}
}

SUBURB_NAME_TO_ID = {v["name"]: v["id"] for v in SUBURBS.values()}


# -------------------------------------------------------------------
# CORE LOGIC
# -------------------------------------------------------------------

def check_property_in_price_range(
    target_address,
    min_price,
    max_price,
    suburb_id,
    max_results=500,
    bedrooms=None,
    bathrooms=None,
    carspaces=None
):
    """
    Check if a property appears in search results for a given price range.
    Returns True if found, False otherwise.
    """
    url = 'https://bff.homely.com.au/graphql'

    headers = {
        'accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.homely.com.au',
        'priority': 'u=1, i'
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
                "max": max_price
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
                "includeSurroundingSuburbs": True
            },
            "paging": {
                "skip": skip,
                "take": results_per_page
            },
            "context": "location",
            "searchMode": "sold",
            "sortBy": "soldHomesForYou",
            "__typename": "SearchParams"
        }

        query_str = "searchParamsJSON=" + json.dumps(search_params, separators=(',', ':'))

        payload = {
            "operationName": "listingMapMarkerSearch",
            "variables": {
                "query": query_str
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "f51020d6110a7a6730645cb8bcdd2a344462684c344b8d88836d7588d3bc39b8"
                }
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    print(f"    ⚠️ Invalid JSON response: {e}")
                    time.sleep(2)
                    continue

                listings = None
                if 'data' in response_data and 'listingSearch' in response_data['data']:
                    listings = response_data['data']['listingSearch'].get('listings', [])
                elif 'data' in response_data and 'listingMapMarkerSearch' in response_data['data']:
                    listings = response_data['data']['listingMapMarkerSearch'].get('results', [])

                if not listings:
                    break  # No more results in this range

                for listing in listings:
                    address_text = None
                    if 'location' in listing and 'address' in listing['location']:
                        address_text = listing['location']['address']
                    elif 'address' in listing:
                        if isinstance(listing['address'], dict):
                            address_text = listing['address'].get('display', '')
                        else:
                            address_text = listing['address']

                    if address_text:
                        address_normalized = address_text.lower().strip()
                        if target_normalized in address_normalized:
                            return True

            # Small delay to avoid rate limiting
            if page < pages_to_check - 1:
                time.sleep(0.3)

        except requests.exceptions.Timeout:
            time.sleep(2)
            continue
        except requests.exceptions.ConnectionError:
            time.sleep(3)
            continue
        except Exception as e:
            print(f"    ⚠️ Unexpected error: {e}")
            time.sleep(1.5)
            continue

    return False


def refine_to_10k_window(
    target_address,
    suburb_id,
    suburb_name,
    min_price,
    max_price,
    max_results=500,
    bedrooms=None,
    bathrooms=None,
    carspaces=None
):
    """Refine a price bracket down to a ~10K window using binary splitting."""
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
            carspaces=carspaces
        )
        queries_made += 1

        if found:
            hi = mid
        else:
            lo = mid + 1

    # Snap to a clean 10K band
    centre = (lo + hi) // 2
    low_band = (centre // 10000) * 10000
    high_band = low_band + 10000

    return {
        'min_price': low_band,
        'max_price': high_band,
        'bracket_width': high_band - low_band,
        'queries_made': queries_made
    }


def binary_search_price_range(
    target_address,
    suburb_id,
    suburb_name,
    price_points=PRICE_POINTS,
    max_results=500,
    find_exact=False,
    bedrooms=None,
    bathrooms=None,
    carspaces=None
):
    """Use binary search to find the price range of a property."""
    min_possible = price_points[0]
    max_possible = price_points[-1]
    queries_made = 0

    # 1. Verify existence
    exists = check_property_in_price_range(
        target_address,
        min_possible,
        max_possible,
        suburb_id,
        max_results=max_results,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        carspaces=carspaces
    )
    queries_made += 1

    if not exists:
        return {
            'found': False,
            'message': 'Property not found in database or address/filters are incorrect',
            'suburb': suburb_name,
            'address': target_address
        }

    # 2. Lower bound
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
            carspaces=carspaces
        )
        queries_made += 1
        if found:
            lower_bound_index = mid
            lo = mid + 1
        else:
            hi = mid - 1

    lower_bound = price_points[lower_bound_index]

    # 3. Upper bound
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
            carspaces=carspaces
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

    # 4. Optional refinement
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
            carspaces=carspaces
        )
        total_queries = queries_made + refine_result['queries_made']
        return {
            'found': True,
            'exact': True,
            'price': None,
            'min_price': refine_result['min_price'],
            'max_price': refine_result['max_price'],
            'bracket_width': refine_result['bracket_width'],
            'queries_made': total_queries,
            'address': target_address,
            'suburb': suburb_name
        }

    # 5. Standard result
    return {
        'found': True,
        'exact': False,
        'price': None,
        'min_price': final_min,
        'max_price': final_max,
        'bracket_width': final_max - final_min,
        'queries_made': queries_made,
        'address': target_address,
        'suburb': suburb_name
    }


# -------------------------------------------------------------------
# CSV HELPERS
# -------------------------------------------------------------------

def parse_uploaded_csv(uploaded_file):
    """
    Parse an uploaded CSV file-like object from Streamlit.
    """
    expected_headers = ['address', 'bedrooms', 'bathrooms', 'carspaces']
    rows = []

    try:
        uploaded_file.seek(0)
        text = uploaded_file.read().decode('utf-8')
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
            address = (row.get('address') or '').strip()
            if not address:
                st.warning(f"Line {idx}: empty address, skipping row.")
                continue

            def parse_int_field(key):
                val = (row.get(key) or '').strip()
                if val == '':
                    return None
                try:
                    return int(val)
                except ValueError:
                    st.warning(
                        f"Line {idx}: invalid integer for '{key}' -> '{val}', "
                        f"treating as 'any'."
                    )
                    return None

            rows.append({
                'address': address,
                'bedrooms': parse_int_field('bedrooms'),
                'bathrooms': parse_int_field('bathrooms'),
                'carspaces': parse_int_field('carspaces')
            })

        return rows

    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        return []


# -------------------------------------------------------------------
# STREAMLIT UI LAYER
# -------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Homely Hidden Price Discovery",
        page_icon="💰",
        layout="wide",
    )

    st.title("💰 Homely Hidden Price Discovery Tool")
    st.write(
        "Discover the hidden sold price range of properties with undisclosed prices, "
        "using binary search over Homely sold data."
    )

    # Sidebar controls
    st.sidebar.header("Settings")

    suburb_name = st.sidebar.selectbox(
        "Suburb",
        options=list(SUBURB_NAME_TO_ID.keys()),
        index=list(SUBURB_NAME_TO_ID.keys()).index("Cronulla") if "Cronulla" in SUBURB_NAME_TO_ID else 0
    )
    suburb_id = SUBURB_NAME_TO_ID[suburb_name]
    st.sidebar.caption(f"Suburb ID: `{suburb_id}`")

    refine_to_10k = st.sidebar.checkbox(
        "Refine to 10K price window",
        value=True,
        help="If checked, the search will be refined down to a ~$10,000 price band."
    )

    max_results = st.sidebar.slider(
        "Max results per search",
        min_value=100,
        max_value=1000,
        value=500,
        step=100,
        help="Maximum number of results to scan per Homely query."
    )

    mode = st.sidebar.radio(
        "Mode",
        options=["Single property", "Batch via CSV"],
        index=0
    )

    if mode == "Single property":
        run_single_property_ui(suburb_name, suburb_id, refine_to_10k, max_results)
    else:
        run_batch_csv_ui(suburb_name, suburb_id, refine_to_10k, max_results)


def run_single_property_ui(suburb_name, suburb_id, refine_to_10k, max_results):
    st.subheader("🏠 Single Property Search")

    col1, col2 = st.columns([2, 1])

    with col1:
        address = st.text_input(
            "Property address",
            placeholder="e.g. G01/79 Gerrale Street, Cronulla NSW 2230"
        )

    with col2:
        st.markdown("**Optional filters**")
        beds = st.number_input("Bedrooms (0 = any)", min_value=0, step=1, value=0)
        baths = st.number_input("Bathrooms (0 = any)", min_value=0, step=1, value=0)
        cars = st.number_input("Car spaces (0 = any)", min_value=0, step=1, value=0)

    bedrooms = beds or None
    bathrooms = baths or None
    carspaces = cars or None

    if st.button("🔍 Run search"):
        if not address.strip():
            st.error("Please enter a property address.")
            return

        with st.spinner("Running price discovery..."):
            result = binary_search_price_range(
                address.strip(),
                suburb_id,
                suburb_name,
                max_results=max_results,
                find_exact=refine_to_10k,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                carspaces=carspaces
            )

        if not result.get('found'):
            st.error(
                "Property not found with the given address/filters.\n\n"
                "Try loosening filters or double-checking the address."
            )
            return

        if result.get('exact'):
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
            f"**Suburb:** {suburb_name}  |  "
            f"**Bracket width:** ${result['bracket_width']:,}  |  "
            f"**API queries:** {result['queries_made']}"
        )


def run_batch_csv_ui(suburb_name, suburb_id, refine_to_10k, max_results):
    st.subheader("📂 Batch Search via CSV")

    st.markdown(
        """
        Upload a CSV file with exactly this header:
        ```csv
        address,bedrooms,bathrooms,carspaces
        G01/79 Gerrale Street, Cronulla NSW 2230,3,3,2
        12 Smith St, Caringbah NSW 2229,3,2,1
        ...
        address is required
        bedrooms, bathrooms, carspaces may be left blank (treated as "any")
        """
    )

    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

    if not uploaded_file:
        st.info("Upload a CSV file to start batch processing.")
        return

    rows = parse_uploaded_csv(uploaded_file)
    if not rows:
        return

    st.success(f"Loaded {len(rows)} properties from CSV.")
    df_preview = pd.DataFrame(rows)
    st.dataframe(df_preview.head(10), use_container_width=True)
    st.caption("Preview of first 10 rows.")

    if not st.button("🚀 Run batch search"):
        return

    results = []
    total = len(rows)
    progress = st.progress(0)
    status = st.empty()

    with st.spinner("Processing properties..."):
        for idx, row in enumerate(rows, start=1):
            address = row['address']
            bedrooms = row['bedrooms']
            bathrooms = row['bathrooms']
            carspaces = row['carspaces']

            status.text(
                f"Processing {idx}/{total}: {address} "
                f"(Beds: {bedrooms or 'any'}, Baths: {bathrooms or 'any'}, Cars: {carspaces or 'any'})"
            )

            result = binary_search_price_range(
                address,
                suburb_id,
                suburb_name,
                max_results=max_results,
                find_exact=refine_to_10k,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                carspaces=carspaces
            )

            if not result.get('found'):
                result_row = {
                    'Address': address,
                    'Suburb': suburb_name,
                    'Found': False,
                    'TenKWindowMode': refine_to_10k,
                    'Price': '',
                    'Min Price': '',
                    'Max Price': '',
                    'Bracket Width': '',
                    'Queries Made': result.get('queries_made', ''),
                    'Error': result.get('message', 'Not found')
                }
            else:
                result_row = {
                    'Address': address,
                    'Suburb': suburb_name,
                    'Found': True,
                    'TenKWindowMode': result.get('exact', False),
                    'Price': result.get('price', ''),
                    'Min Price': result.get('min_price', ''),
                    'Max Price': result.get('max_price', ''),
                    'Bracket Width': result.get('bracket_width', ''),
                    'Queries Made': result.get('queries_made', ''),
                    'Error': ''
                }

            results.append(result_row)
            progress.progress(min(int(idx * 100 / total), 100))

            # polite delay to avoid hammering the API
            time.sleep(0.3)

    status.text("Batch processing complete.")

    df_results = pd.DataFrame(results)
    st.subheader("📊 Results")
    st.dataframe(df_results, use_container_width=True)

    csv_bytes = df_results.to_csv(index=False).encode('utf-8')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"price_discovery_{suburb_name.replace(' ', '')}{timestamp}.csv"

    st.download_button(
        label="💾 Download results as CSV",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv"
    )

    st.success("Done! You can now download the results.")


if __name__ == "__main__":
    main()
