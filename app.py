import streamlit as st
import requests
import json
import time

# ---------------------------
# ORIGINAL WORKING CODE (UNTOUCHED)
# ---------------------------

PRICE_POINTS = [
    200000, 250000, 300000, 350000, 400000, 450000, 500000, 550000, 600000, 700000,
    750000, 800000, 850000, 900000, 950000, 1000000, 1100000, 1200000, 1300000, 1400000,
    1500000, 1600000, 1700000, 1800000, 1900000, 2000000, 2250000, 2500000, 2750000,
    3500000, 4000000, 4500000, 5000000, 6000000, 7000000, 8000000, 9000000, 10000000
]

SUBURB_ID = 5710793  # Cronulla (hardcoded exactly like your working script)


def check_property_in_price_range(target_address, min_price, max_price, max_results=100):
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
            "bathrooms": None,
            "bedrooms": None,
            "carSpaces": None,
            "propertyFeatures": [],
            "propertyTypes": [],
            "inspection": None,
            "auction": None,
            "frontageSize": None,
            "landSize": None,
            "isUnderOffer": None,
            "locationSearchContext": {
                "__typename": "SuburbsSearch",
                "searchLocations": [{"id": SUBURB_ID}],
                "includeSurroundingSuburbs": False
            },
            "paging": {"skip": skip, "take": results_per_page},
            "context": "location",
            "searchMode": "sold",
            "sortBy": "recentlySoldOrLeased",
            "__typename": "SearchParams"
        }

        query_str = "searchParamsJSON=" + json.dumps(search_params, separators=(',', ':'))

        payload = {
            "operationName": "listingMapMarkerSearch",
            "variables": {"query": query_str},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "f51020d6110a7a6730645cb8bcdd2a344462684c344b8d88836d7588d3bc39b8"
                }
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                continue

            data = response.json()

            listings = None
            if "listingSearch" in data.get("data", {}):
                listings = data["data"]["listingSearch"].get("listings", [])
            elif "listingMapMarkerSearch" in data.get("data", {}):
                listings = data["data"]["listingMapMarkerSearch"].get("results", [])

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

                if address_text and target_normalized in address_text.lower():
                    return True

            time.sleep(0.3)

        except Exception:
            time.sleep(1)

    return False


def binary_search_price_range(target_address, price_points=PRICE_POINTS, max_results=100):
    min_possible = price_points[0]
    max_possible = price_points[-1]

    if not check_property_in_price_range(target_address, min_possible, max_possible, max_results):
        return {'found': False}

    queries = 1
    left = 0
    right = len(price_points) - 1
    lower_bound_index = 0

    while left < right:
        mid = (left + right) // 2
        test_min = price_points[mid]

        found = check_property_in_price_range(target_address, test_min, max_possible, max_results)
        queries += 1

        if found:
            lower_bound_index = mid
            left = mid + 1
        else:
            right = mid

    left = lower_bound_index
    right = len(price_points) - 1
    upper_bound_index = right

    while left < right:
        mid = (left + right) // 2
        test_max = price_points[mid]

        found = check_property_in_price_range(target_address, min_possible, test_max, max_results)
        queries += 1

        if found:
            upper_bound_index = mid
            right = mid
        else:
            left = mid + 1

    low_price = price_points[lower_bound_index]
    high_price = price_points[upper_bound_index]

    return {
        'found': True,
        'min_price': low_price,
        'max_price': high_price,
        'queries': queries
    }


# ---------------------------
# STREAMLIT UI
# ---------------------------

st.title("🏠 Homely Hidden Price Discovery Tool")
st.write("Enter a property address in **Cronulla** and this tool will estimate the hidden sold price.")

st.divider()

address = st.text_input("Enter the property address (e.g. '5 Surf Road')")

run_search = st.button("Search Price Range")

if run_search:
    if not address.strip():
        st.error("Please enter an address.")
    else:
        with st.spinner("Searching Homely..."):
            result = binary_search_price_range(address)

        if not result["found"]:
            st.error("❌ Property not found in any price bracket.")
        else:
            st.success("Price range discovered!")
            st.metric("Minimum Price", f"${result['min_price']:,}")
            st.metric("Maximum Price", f"${result['max_price']:,}")
            st.write(f"🔍 **API Queries Used:** {result['queries']}")
