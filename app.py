import streamlit as st
import requests
import json
import time
import csv
from datetime import datetime
from io import StringIO
import pandas as pd

# Predefined price points for binary search
PRICE_POINTS = [
    200000, 250000, 300000, 350000, 400000, 450000, 500000, 550000, 600000, 700000,
    750000, 800000, 850000, 900000, 950000, 1000000, 1100000, 1200000, 1300000, 1400000,
    1500000, 1600000, 1700000, 1800000, 1900000, 2000000, 2250000, 2500000, 2750000, 3000000,
    3500000, 4000000, 4500000, 5000000, 6000000, 7000000, 8000000, 9000000, 10000000
]

# Available suburbs with their search location IDs
SUBURBS = {
    "Caringbah": {"id": 5710753},
    "Caringbah South": {"id": 6215183},
    "Dolans Bay": {"id": 5710812},
    "Taren Point": {"id": 5711145},
    "Cronulla": {"id": 5710793},
    "Port Hacking": {"id": 6217567}
}


def check_property_in_price_range(
    target_address,
    min_price,
    max_price,
    suburb_id,
    max_results=500,
    bedrooms=None,
    bathrooms=None,
    carspaces=None,
    progress_callback=None
):
    """Check if a property appears in search results for a given price range."""
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

        # Build the query string exactly as the API expects it
        search_params_dict = {
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

        # Convert to JSON string and wrap in searchParamsJSON=
        search_params_json = json.dumps(search_params_dict, separators=(',', ':'))
        query_str = f'searchParamsJSON={search_params_json}'

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
                    if progress_callback:
                        progress_callback(f"JSON decode error: {str(e)[:50]}")
                    time.sleep(2)
                    continue

                listings = None
                if 'data' in response_data and 'listingSearch' in response_data['data']:
                    listings = response_data['data']['listingSearch'].get('listings', [])
                elif 'data' in response_data and 'listingMapMarkerSearch' in response_data['data']:
                    listings = response_data['data']['listingMapMarkerSearch'].get('results', [])

                if listings is None or len(listings) == 0:
                    break  # No more results

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

            else:
                if progress_callback:
                    progress_callback(f"API returned status {response.status_code}")
                time.sleep(2)
                continue

            if page < pages_to_check - 1:
                time.sleep(0.3)

        except requests.exceptions.Timeout:
            if progress_callback:
                progress_callback("Request timeout - retrying...")
            time.sleep(2)
            continue
        except requests.exceptions.ConnectionError:
            if progress_callback:
                progress_callback("Connection error - retrying...")
            time.sleep(3)
            continue
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {str(e)[:50]}")
            time.sleep(1.5)
            continue

    return False


def refine_to_10k_window(
    target_address,
    suburb_id,
    min_price,
    max_price,
    max_results=500,
    bedrooms=None,
    bathrooms=None,
    carspaces=None,
    progress_callback=None
):
    """Refine a price bracket down to a ~10K window using binary splitting."""
    queries_made = 0
    lo = min_price
    hi = max_price

    while hi - lo > 10000:
        mid = (lo + hi) // 2
        
        if progress_callback:
            progress_callback(f"Refining: ${lo:,} - ${mid:,}")
        
        found = check_property_in_price_range(
            target_address, lo, mid, suburb_id, max_results,
            bedrooms, bathrooms, carspaces
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
    carspaces=None,
    progress_callback=None
):
    """Use binary search to find the price range of a property."""
    
    if progress_callback:
        progress_callback("Step 1: Verifying property exists...")
    
    min_possible = price_points[0]
    max_possible = price_points[-1]
    queries_made = 0

    exists = check_property_in_price_range(
        target_address, min_possible, max_possible, suburb_id,
        max_results, bedrooms, bathrooms, carspaces
    )
    queries_made += 1

    if not exists:
        return {
            'found': False,
            'message': 'Property not found in database or filters are incorrect',
            'suburb': suburb_name,
            'address': target_address
        }

    # Binary search for lower bound
    if progress_callback:
        progress_callback("Step 2: Finding lower price bound...")
    
    lo = 0
    hi = len(price_points) - 1
    lower_bound_index = 0

    while lo <= hi:
        mid = (lo + hi) // 2
        threshold = price_points[mid]

        found = check_property_in_price_range(
            target_address, threshold, max_possible, suburb_id,
            max_results, bedrooms, bathrooms, carspaces
        )
        queries_made += 1

        if found:
            lower_bound_index = mid
            lo = mid + 1
        else:
            hi = mid - 1

    lower_bound = price_points[lower_bound_index]

    # Binary search for upper bound
    if progress_callback:
        progress_callback("Step 3: Finding upper price bound...")
    
    lo = 0
    hi = len(price_points) - 1
    upper_bound_index = len(price_points) - 1

    while lo <= hi:
        mid = (lo + hi) // 2
        threshold = price_points[mid]

        found = check_property_in_price_range(
            target_address, min_possible, threshold, suburb_id,
            max_results, bedrooms, bathrooms, carspaces
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
        if progress_callback:
            progress_callback("Step 4: Refining to 10K window...")
        
        refine_result = refine_to_10k_window(
            target_address, suburb_id, final_min, final_max,
            max_results, bedrooms, bathrooms, carspaces, progress_callback
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


# Streamlit App
def main():
    st.set_page_config(
        page_title="Homely Price Discovery",
        page_icon="🏠",
        layout="wide"
    )

    st.title("🏠 Homely Hidden Price Discovery Tool")
    st.markdown("Discover undisclosed property prices using binary search")

    # Sidebar for configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Debug mode
    debug_mode = st.sidebar.checkbox("🐛 Debug Mode", value=False)
    
    # Suburb selection
    suburb_name = st.sidebar.selectbox(
        "Select Suburb",
        options=list(SUBURBS.keys())
    )
    suburb_id = SUBURBS[suburb_name]["id"]
    
    st.sidebar.success(f"Selected: {suburb_name} (ID: {suburb_id})")

    # Mode selection
    mode = st.sidebar.radio(
        "Select Mode",
        options=["Single Property", "Batch (CSV Upload)"]
    )

    # Main content area
    if mode == "Single Property":
        st.header("🔍 Single Property Search")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            address = st.text_input(
                "Property Address",
                placeholder="e.g., 79 Gerrale Street, Cronulla"
            )
        
        with col2:
            find_exact = st.checkbox("Refine to 10K window", value=False)
        
        # Property filters
        st.subheader("🔧 Optional Filters (speeds up search)")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            bedrooms = st.number_input("Bedrooms", min_value=0, max_value=10, value=0, step=1)
            bedrooms = bedrooms if bedrooms > 0 else None
        
        with col2:
            bathrooms = st.number_input("Bathrooms", min_value=0, max_value=10, value=0, step=1)
            bathrooms = bathrooms if bathrooms > 0 else None
        
        with col3:
            carspaces = st.number_input("Car Spaces", min_value=0, max_value=10, value=0, step=1)
            carspaces = carspaces if carspaces > 0 else None
        
        # Search button
        if st.button("🔎 Search", type="primary"):
            if not address:
                st.error("❌ Please enter a property address")
            else:
                # Progress tracking
                progress_bar = st.progress(0)
                status_text = st.empty()
                debug_container = st.expander("🔍 Debug Information") if debug_mode else None
                
                def update_progress(message):
                    status_text.info(message)
                    if debug_mode and debug_container:
                        with debug_container:
                            st.text(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
                
                with st.spinner("Searching..."):
                    result = binary_search_price_range(
                        address,
                        suburb_id,
                        suburb_name,
                        find_exact=find_exact,
                        bedrooms=bedrooms,
                        bathrooms=bathrooms,
                        carspaces=carspaces,
                        progress_callback=update_progress
                    )
                
                progress_bar.progress(100)
                status_text.empty()
                
                # Display results
                if result['found']:
                    st.success("✅ Property Found!")
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Min Price", f"${result['min_price']:,}")
                    
                    with col2:
                        st.metric("Max Price", f"${result['max_price']:,}")
                    
                    with col3:
                        st.metric("Bracket Width", f"${result['bracket_width']:,}")
                    
                    st.info(f"📊 Total API Queries: {result['queries_made']}")
                    
                    if result.get('exact'):
                        st.success("🎯 Refined to 10K price window!")
                    
                    # Display details
                    with st.expander("📋 Result Details"):
                        st.write(f"**Address:** {result['address']}")
                        st.write(f"**Suburb:** {result['suburb']}")
                        st.write(f"**Price Range:** ${result['min_price']:,} - ${result['max_price']:,}")
                        st.write(f"**Queries Made:** {result['queries_made']}")
                else:
                    st.error("❌ Property not found")
                    st.warning(result.get('message', 'Property not in database'))
                    
                    if debug_mode:
                        with st.expander("🐛 Debug Info"):
                            st.json(result)

    else:  # Batch CSV Upload
        st.header("📊 Batch Processing (CSV Upload)")
        
        st.info("📄 CSV format required: `address,bedrooms,bathrooms,carspaces`")
        
        # Show example
        with st.expander("📝 View CSV Example"):
            st.code("""address,bedrooms,bathrooms,carspaces
79 Gerrale Street Cronulla,3,2,2
123 Main Street Sydney,4,3,2
456 Ocean Drive Bondi,2,1,1""")
        
        find_exact = st.checkbox("Refine to 10K windows", value=False)
        
        uploaded_file = st.file_uploader("Choose CSV file", type=['csv'])
        
        if uploaded_file is not None:
            try:
                # Read CSV
                df = pd.read_csv(uploaded_file)
                
                # Validate columns
                required_cols = ['address', 'bedrooms', 'bathrooms', 'carspaces']
                if list(df.columns) != required_cols:
                    st.error(f"❌ CSV must have columns: {', '.join(required_cols)}")
                else:
                    st.success(f"✅ Loaded {len(df)} properties")
                    
                    # Show preview
                    with st.expander("👀 Preview Data"):
                        st.dataframe(df)
                    
                    if st.button("🚀 Start Batch Processing", type="primary"):
                        results = []
                        
                        # Progress tracking
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        results_container = st.container()
                        
                        for idx, row in df.iterrows():
                            address = row['address']
                            bedrooms = None if pd.isna(row['bedrooms']) else int(row['bedrooms'])
                            bathrooms = None if pd.isna(row['bathrooms']) else int(row['bathrooms'])
                            carspaces = None if pd.isna(row['carspaces']) else int(row['carspaces'])
                            
                            status_text.info(f"Processing {idx + 1}/{len(df)}: {address}")
                            
                            def update_progress(message):
                                status_text.info(f"Property {idx + 1}/{len(df)}: {message}")
                            
                            result = binary_search_price_range(
                                address,
                                suburb_id,
                                suburb_name,
                                find_exact=find_exact,
                                bedrooms=bedrooms,
                                bathrooms=bathrooms,
                                carspaces=carspaces,
                                progress_callback=update_progress
                            )
                            
                            results.append(result)
                            progress_bar.progress((idx + 1) / len(df))
                            
                            if idx < len(df) - 1:
                                time.sleep(2)
                        
                        status_text.success("✅ Batch processing complete!")
                        progress_bar.empty()
                        
                        # Display results table
                        st.subheader("📊 Results Summary")
                        
                        results_data = []
                        for r in results:
                            results_data.append({
                                'Address': r.get('address', 'N/A'),
                                'Found': '✅' if r.get('found') else '❌',
                                'Min Price': f"${r.get('min_price', 0):,}" if r.get('found') else 'N/A',
                                'Max Price': f"${r.get('max_price', 0):,}" if r.get('found') else 'N/A',
                                'Width': f"${r.get('bracket_width', 0):,}" if r.get('found') else 'N/A',
                                'Queries': r.get('queries_made', 'N/A')
                            })
                        
                        results_df = pd.DataFrame(results_data)
                        st.dataframe(results_df, use_container_width=True)
                        
                        # Download results
                        csv_buffer = StringIO()
                        results_df.to_csv(csv_buffer, index=False)
                        
                        st.download_button(
                            label="📥 Download Results (CSV)",
                            data=csv_buffer.getvalue(),
                            file_name=f"price_discovery_{suburb_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                        
                        # Statistics
                        found_count = sum(1 for r in results if r.get('found'))
                        total_queries = sum(r.get('queries_made', 0) for r in results)
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Properties Found", f"{found_count}/{len(results)}")
                        with col2:
                            st.metric("Total Queries", total_queries)
                        with col3:
                            avg_queries = total_queries / len(results) if results else 0
                            st.metric("Avg Queries/Property", f"{avg_queries:.1f}")
                        
            except Exception as e:
                st.error(f"❌ Error reading CSV: {e}")
    
    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📖 How It Works")
    st.sidebar.markdown("""
    1. **Binary Search**: Quickly narrows down price brackets
    2. **10K Refinement**: Optional fine-tuning to ±$5K
    3. **Filters**: Speed up search with property features
    """)
    
    st.sidebar.markdown("### 💡 Tips")
    st.sidebar.markdown("""
    - Use filters for faster results
    - 10K refinement takes more queries
    - Batch mode for multiple properties
    """)


if __name__ == "__main__":
    main()
