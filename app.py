import streamlit as st
import requests
import json
import time

# Minimal suburbs
SUBURBS = {
    "Caringbah": 5710753,
    "Caringbah South": 6215183,
    "Dolans Bay": 5710812,
    "Taren Point": 5711145,
    "Cronulla": 5710793,
    "Port Hacking": 6217567,
}

# Very simple bare-bones API call
def test_api_find_property(address, suburb_id):
    target = address.lower().strip()

    url = "https://bff.homely.com.au/graphql"
    headers = {
        'accept': '*/*',
        'Origin': 'https://www.homely.com.au'
    }

    # Hard-coded simple wide price range for testing
    search_params = {
        "price": {
            "__typename": "MinAndMaxFilter",
            "min": 200000,
            "max": 10000000
        },
        "locationSearchContext": {
            "__typename": "SuburbsSearch",
            "searchLocations": [{"id": suburb_id}],
            "includeSurroundingSuburbs": True
        },
        "paging": {"skip": 0, "take": 25},
        "context": "location",
        "searchMode": "sold",
        "sortBy": "recentlySoldOrLeased",
        "__typename": "SearchParams"
    }

    payload = {
        "operationName": "listingMapMarkerSearch",
        "variables": {"query": "searchParamsJSON=" + json.dumps(search_params)},
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "f51020d6110a7a6730645cb8bcdd2a344462684c344b8d88836d7588d3bc39b8"
            }
        }
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=25)

        if r.status_code != 200:
            return f"HTTP {r.status_code}", None

        data = r.json()
        listings = None

        # Homely sometimes returns under listingSearch, sometimes listingMapMarkerSearch
        if "data" in data and "listingMapMarkerSearch" in data["data"]:
            listings = data["data"]["listingMapMarkerSearch"].get("results", [])
        if listings is None and "listingSearch" in data.get("data", {}):
            listings = data["data"]["listingSearch"].get("listings", [])

        if not listings:
            return "No results returned", None

        for item in listings:
            addr = None

            if "location" in item and "address" in item["location"]:
                addr = item["location"]["address"]
            elif "address" in item:
                a = item["address"]
                addr = a.get("display") if isinstance(a, dict) else a

            if addr and target in addr.lower():
                return "FOUND", addr

        return "NOT FOUND", None

    except Exception as e:
        return f"Error: {e}", None


# ----------------------------
# STREAMLIT UI
# ----------------------------
st.title("🔍 Homely API Test (Simple Mode)")
st.write("This minimal version checks if ANY result is returned by the Homely API.")

suburb = st.selectbox("Select suburb", list(SUBURBS.keys()))
address = st.text_input("Enter address to search for")

if st.button("Test API"):
    if not address.strip():
        st.error("Please enter an address.")
    else:
        st.info("Contacting Homely API…")

        status, matched_address = test_api_find_property(address, SUBURBS[suburb])

        if status == "FOUND":
            st.success(f"🎉 MATCHED ADDRESS: {matched_address}")
        elif status == "NOT FOUND":
            st.warning("❌ No matching property found in the returned results.")
        else:
            st.error(f"⚠️ API Response: {status}")

        st.caption("This checks only the first 25 results in the suburb.")
