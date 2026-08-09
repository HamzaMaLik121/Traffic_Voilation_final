"""
Streamlit Web Dashboard -- Traffic Violation Detection System
Rewritten to call the API service via HTTP instead of importing the database directly.

Run with:  streamlit run app/dashboard.py
"""

import os
import sys
from pathlib import Path
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# API URL from environment variable (set in docker-compose / Kubernetes)
API_URL = os.getenv("API_URL", "http://api:5000")

# External URL for browser-side content (MJPEG stream - browser reaches this directly)
# Default to localhost:5001 which is the mapped port in docker-compose
STREAM_URL = os.getenv("STREAM_URL", "http://localhost:5001")

# Violation type labels
VIOLATIONS = {
    "NO_HELMET": "No Helmet Violation",
    "RED_LIGHT": "Red Light Violation",
    "OVER_SPEED": "Over Speeding",
    "LANE_VIOLATION": "Lane Violation",
    "ILLEGAL_UTURN": "Illegal U-Turn"
}

def get_request_host():
    """Return the hostname/IP the browser used to reach this page,
    read from the incoming request's Host header via Streamlit's
    official st.context API. Falls back to localhost if unavailable."""
    try:
        host_header = st.context.headers.get("Host", "localhost:8501")
        return host_header.split(":")[0]
    except Exception:
        return "localhost"


DASHBOARD_TITLE = "Traffic Violation Detection System"

# ── optional charting ─────────────────────────────────────────────────
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ── page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title=DASHBOARD_TITLE,
    page_icon="TV",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem; font-weight: 800; text-align: center;
        background: linear-gradient(90deg,#e74c3c,#e67e22,#f1c40f);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        padding: 0.5rem 0 1.5rem;
    }
    .metric-box {
        background: #1e1e2e; border-radius: 12px; padding: 1.1rem 1.5rem;
        border-left: 5px solid #e74c3c; color: white;
    }
    .violation-badge {
        display:inline-block; padding:2px 10px; border-radius:12px;
        background:#e74c3c; color:white; font-size:0.75rem;
    }
</style>
""", unsafe_allow_html=True)


# ── API helper functions ──────────────────────────────────────────────

@st.cache_data(ttl=5)
def fetch_violations(filters=None, limit=200):
    """Fetch violations from the API"""
    params = {'limit': limit}
    if filters:
        if 'violation_type' in filters:
            params['violation_type'] = filters['violation_type']
        if 'license_plate' in filters:
            params['license_plate'] = filters['license_plate']
        if 'start_date' in filters:
            params['start_date'] = filters['start_date'].isoformat() if hasattr(filters['start_date'], 'isoformat') else filters['start_date']
        if 'end_date' in filters:
            params['end_date'] = filters['end_date'].isoformat() if hasattr(filters['end_date'], 'isoformat') else filters['end_date']
    
    try:
        resp = requests.get(f"{API_URL}/violations", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get('violations', [])
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Could not reach API: {e}")
        return []


@st.cache_data(ttl=30)
def fetch_statistics(start_date=None, end_date=None):
    """Fetch violation statistics from the API"""
    params = {}
    if start_date:
        params['start_date'] = start_date.isoformat() if hasattr(start_date, 'isoformat') else start_date
    if end_date:
        params['end_date'] = end_date.isoformat() if hasattr(end_date, 'isoformat') else end_date
    
    try:
        resp = requests.get(f"{API_URL}/statistics", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get('statistics', {})
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Could not reach API: {e}")
        return {}


@st.cache_data(ttl=10)
def fetch_violation_by_id(violation_id):
    """Fetch a single violation by ID from the API"""
    try:
        resp = requests.get(f"{API_URL}/violations/{violation_id}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"⚠️ Could not fetch violation #{violation_id}: {e}")
        return None


@st.cache_data(ttl=5)
def fetch_worker_status():
    """Fetch the worker's current processing status from the API"""
    try:
        resp = requests.get(f"{API_URL}/worker-status", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return {'status': 'offline', 'worker_heartbeat_age': -1, 'violations_count': 0}


# ══════════════════════════════════════════════════════════════════════
#  PAGES
# ══════════════════════════════════════════════════════════════════════

def page_dashboard():
    st.markdown('<p class="main-header">Traffic Violation Detection System</p>',
                unsafe_allow_html=True)

    # ── sidebar filters ───────────────────────────────────────────────
    st.sidebar.header("Filters")

    date_range = st.sidebar.date_input(
        "Date range",
        value=(datetime.now().date() - timedelta(days=7), datetime.now().date()),
        max_value=datetime.now().date(),
    )

    all_types = list(VIOLATIONS.keys())
    selected_types = st.sidebar.multiselect(
        "Violation types", options=all_types,
        default=all_types,
        format_func=lambda k: VIOLATIONS.get(k, k),
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    # ── fetch data ────────────────────────────────────────────────────
    filters = {}
    if len(date_range) == 2:
        filters['start_date'] = datetime.combine(date_range[0], datetime.min.time())
        filters['end_date']   = datetime.combine(date_range[1], datetime.max.time())

    stats = fetch_statistics(
        start_date=filters.get('start_date'),
        end_date=filters.get('end_date'),
    )
    today_stats = fetch_statistics(
        start_date=datetime.now().replace(hour=0, minute=0, second=0),
        end_date=datetime.now(),
    )

    # ── KPI row ───────────────────────────────────────────────────────
    st.subheader("Overview")
    c1, c2, c3, c4 = st.columns(4)

    total = sum(stats.values())
    today = sum(today_stats.values())
    most_type, most_count = max(stats.items(), key=lambda x: x[1]) if stats else ("—", 0)

    c1.metric("Total Violations", total)
    c2.metric("Today", today)
    c3.metric("Types Detected", len([v for v in stats.values() if v > 0]))
    c4.metric("Most Common",
              VIOLATIONS.get(most_type, most_type) if most_type != "—" else "—",
              f"{most_count} cases" if most_count else None)

    # ── charts ────────────────────────────────────────────────────────
    st.subheader("Distribution")

    if stats and HAS_PLOTLY:
        col_a, col_b = st.columns(2)

        labels = [VIOLATIONS.get(k, k) for k in stats]
        values = list(stats.values())

        with col_a:
            fig = px.pie(values=values, names=labels,
                         title="Violation Share",
                         color_discrete_sequence=px.colors.qualitative.Bold)
            st.plotly_chart(fig, width="stretch")

        with col_b:
            fig2 = px.bar(x=labels, y=values,
                          title="Violations by Type",
                          labels={"x": "Type", "y": "Count"},
                          color=values, color_continuous_scale="Reds")
            st.plotly_chart(fig2, width="stretch")

    elif stats:
        st.bar_chart({VIOLATIONS.get(k, k): v for k, v in stats.items()})
    else:
        st.info("No violation data yet. Run the worker service to generate records.")

    # ── violations table ──────────────────────────────────────────────
    st.subheader("Violation Records")

    violations = fetch_violations(filters=filters, limit=200)

    if selected_types:
        violations = [v for v in violations if v['violation_type'] in selected_types]

    if not violations:
        st.info("No violations match the selected filters.")
        return

    df = pd.DataFrame(violations)

    df['violation_label'] = df['violation_type'].map(lambda k: VIOLATIONS.get(k, k))
    if 'confidence' in df.columns:
        df['confidence_pct']  = df['confidence'].map(
            lambda x: f"{x:.1%}" if pd.notna(x) and x else "n/a"
        )
    else:
        df['confidence_pct'] = "n/a"
    if 'speed' in df.columns:
        df['speed_str'] = df['speed'].map(
            lambda x: f"{x:.1f} km/h" if pd.notna(x) and x else "—"
        )
    else:
        df['speed_str'] = "—"

    show_cols = {
        'id': 'ID',
        'violation_label': 'Violation',
        'timestamp': 'Timestamp',
        'license_plate': 'Plate',
        'vehicle_type': 'Vehicle',
        'confidence_pct': 'Confidence',
        'speed_str': 'Speed',
    }
    display_cols = [c for c in show_cols if c in df.columns]
    display_df = df[display_cols].rename(columns=show_cols)

    st.dataframe(display_df, width="stretch", hide_index=True)

    # ── CSV export ────────────────────────────────────────────────────
    csv_bytes = display_df.to_csv(index=False).encode()
    st.download_button(
        label="Export to CSV",
        data=csv_bytes,
        file_name=f"violations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    # ── evidence viewer ───────────────────────────────────────────────
    st.subheader("Evidence Viewer")

    id_options = df['id'].tolist()
    if not id_options:
        return

    sel_id = st.selectbox("Select a violation record",
                           id_options,
                           format_func=lambda x: f"Violation #{x}")

    record = fetch_violation_by_id(sel_id)
    if not record:
        return

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("**Details**")
        for label, key in [
            ("Type",         "violation_type"),
            ("Timestamp",    "timestamp"),
            ("Plate",        "license_plate"),
            ("Vehicle",      "vehicle_type"),
            ("Speed",        "speed"),
            ("Speed Limit",  "speed_limit"),
            ("Frame #",      "video_frame_number"),
        ]:
            val = record.get(key)
            if key == "violation_type":
                val = VIOLATIONS.get(val, val)
            if key in ("speed", "speed_limit") and val:
                val = f"{float(val):.1f} km/h"
            st.write(f"**{label}:** {val if val else '—'}")

    with col2:
        ev_path = record.get('evidence_image_path')
        if ev_path:
            # Try to load the image from the API or local filesystem
            # For the dashboard service, evidence images are on a shared volume at /app/outputs
            local_path = Path(ev_path)
            if local_path.exists():
                st.image(str(local_path), caption="Evidence Image", width="stretch")
            else:
                # If running in separate containers, try fetching via API
                # Note: evidence images are served via shared volume, not HTTP
                st.info("Evidence image not available (check shared volume mount)")
        else:
            st.info("No evidence image saved for this record.")


def page_live():
    st.markdown('<h1 class="main-header">Live Monitoring</h1>', unsafe_allow_html=True)

    # ── control row ──────────────────────────────────────────────────────
    col_status, col_refresh, col_interval = st.columns([3, 1, 2])

    with col_refresh:
        st.button("Refresh Now", type="primary", width="stretch")

    with col_interval:
        auto_refresh = st.toggle("Auto-refresh", value=True,
                                 help="The table and violation counts below update automatically at this interval.")
        refresh_sec  = st.slider("Refresh every (sec)", 3, 30, 5, label_visibility="collapsed")

    # ── auto-refreshing data (status + counts + table) ───────────────────
    # Auto-refresh runs inside a st.fragment(run_every=...) instead of a
    # time.sleep() + st.rerun() loop. Fragments rerun IN PLACE without
    # reloading the whole frontend module graph, which avoids the
    # intermittent browser error "Failed to fetch dynamically imported
    # module" (Checkbox.js, Slider.js chunks) that full-page reruns can
    # trigger. run_every must be a number/timedelta (or None = no auto
    # rerun) — callables are not accepted by this Streamlit version.
    @st.fragment(run_every=refresh_sec if auto_refresh else None)
    def live_data_fragment():
        # ── system status ─────────────────────────────────────────────
        # Uses worker heartbeat (latest_frame.jpg mtime) to determine if the
        # worker is actively processing, regardless of whether violations exist.
        ws = fetch_worker_status()
        worker_status = ws.get('status', 'offline')
        heartbeat_age = ws.get('worker_heartbeat_age', -1)

        if worker_status == 'active':
            status_color = "#2ecc71"
            status_icon  = "[ACTIVE]"
            status_text  = f"Worker ACTIVE — detecting {int(heartbeat_age)}s ago"
        elif worker_status == 'idle':
            status_color = "#f39c12"
            status_icon  = "[IDLE]"
            status_text  = f"Worker IDLE — last heartbeat {int(heartbeat_age)}s ago"
        elif worker_status == 'offline' and heartbeat_age > 0:
            status_color = "#e74c3c"
            status_icon  = "[OFFLINE]"
            status_text  = "Worker OFFLINE — no heartbeat"
        else:
            status_color = "#7f8c8d"
            status_icon  = "[NO DATA]"
            status_text  = "No data — start the worker service to begin detection"

        with col_status:
            st.markdown(
                f'<div style="background:{status_color}22; border-left:5px solid {status_color}; '
                f'border-radius:8px; padding:0.75rem 1.2rem; color:{status_color}; font-weight:700;">'
                f'{status_icon}  {status_text}</div>',
                unsafe_allow_html=True
            )

        st.markdown("")

        # ── live counts ───────────────────────────────────────────────────
        st.subheader("Live Violation Counts")
        all_violations = fetch_violations(limit=5000)
        type_counts = {}
        for v in all_violations:
            vt = v['violation_type']
            type_counts[vt] = type_counts.get(vt, 0) + 1

        count_cols = st.columns(max(1, len(type_counts)) if type_counts else 4)
        icons = {'NO_HELMET': '[H]', 'OVER_SPEED': '[S]', 'RED_LIGHT': '[R]',
                 'LANE_VIOLATION': '[L]', 'ILLEGAL_UTURN': '[U]'}

        if type_counts:
            for i, (vtype, count) in enumerate(sorted(type_counts.items())):
                with count_cols[i % len(count_cols)]:
                    icon = icons.get(vtype, '[V]')
                    label = VIOLATIONS.get(vtype, vtype.replace('_', ' ').title())
                    st.metric(f"{icon} {label}", count)
        else:
            st.info("No violations yet. Start the worker to begin detection.")

        st.markdown("")

        # ── live feed table ───────────────────────────────────────────────
        st.subheader("Latest Violations (Live Feed)")
        recent = fetch_violations(limit=15)

        if recent:
            rows = []
            for v in recent:
                rows.append({
                    'Timestamp':   str(v.get('timestamp', ''))[:19],
                    'Violation':   VIOLATIONS.get(v['violation_type'],
                                   v['violation_type'].replace('_', ' ').title()),
                    'Vehicle':     v.get('vehicle_type') or '—',
                    'Plate':       v.get('license_plate') or '—',
                    'Speed':       f"{v['speed']:.0f} km/h" if v.get('speed') else '—',
                    'Confidence':  f"{v['confidence']:.0%}" if v.get('confidence') else '—',
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Feed is empty -- no violations recorded yet.")

    # ── embedded live stream ─────────────────────────────────────────────
    # The MJPEG <img> is self-updating, so it stays OUTSIDE the auto-refresh
    # fragment — it is never torn down or re-created by periodic refreshes.
    st.subheader("📹 Live Detection Feed")
    stream_src = f"http://{get_request_host()}:5001/mjpeg"

    st.markdown(
        f'''
        <div id="live-feed-container" style="
            border: 2px solid #333;
            border-radius: 12px;
            overflow: hidden;
            max-width: 1280px;
            width: 100%;
            margin: 8px auto 16px;
            background: #000;
            position: relative;
        ">
            <img id="live-feed-img" src="{stream_src}"
                 style="width:100%;height:auto;display:block;"
                 alt="Live detection feed (MJPEG)"
            />
            <div id="live-feed-offline" style="
                display:none;position:absolute;inset:0;
                background:rgba(0,0,0,0.85);
                align-items:center;justify-content:center;
                flex-direction:column;gap:6px;
            ">
                <div style="font-size:2.5rem;">📹</div>
                <div style="font-weight:600;color:#e74c3c;">Feed Offline</div>
                <div style="color:#888;font-size:0.8rem;">
                    Waiting for worker to start processing...
                </div>
            </div>
        </div>
        <script>
        (function() {{
            var img = document.getElementById('live-feed-img');
            var fallback = document.getElementById('live-feed-offline');
            if (!img || !fallback) return;
            img.onerror = function() {{
                img.style.display = 'none';
                fallback.style.display = 'flex';
            }};
            img.onload = function() {{
                img.style.display = 'block';
                fallback.style.display = 'none';
            }};
        }})();
        </script>
        ''',
        unsafe_allow_html=True
    )
    st.caption("The video feed updates live — no auto-refresh needed for the stream itself.")

    # Render the auto-refreshing section (the fragment re-runs in place).
    live_data_fragment()

    # A "Refresh Now" click triggers a full rerun, which also refreshes the
    # fragment content above — no extra logic needed.


def page_settings():
    st.header("Settings")
    st.info("Configuration is controlled via environment variables in the worker service.")

    st.subheader("System Configuration")
    cfg_items = {
        "API URL":          API_URL,
        "Refresh Interval": "5 sec (auto-refresh)",
    }
    st.table(pd.DataFrame(list(cfg_items.items()), columns=["Setting", "Value"]))

    st.markdown("")
    st.subheader("Speed Calibration")
    st.markdown("""
    For accurate speed readings, run the calibration tool in the worker container:
    ```bash
    python tools/calibrate_speed.py
    ```
    """)


# ══════════════════════════════════════════════════════════════════════
#  NAVIGATION
# ══════════════════════════════════════════════════════════════════════

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Live Monitoring", "Settings"])

    if page == "Dashboard":
        page_dashboard()
    elif page == "Live Monitoring":
        page_live()
    else:
        page_settings()

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Developed by:\n- Muhammad Jawad\n- Hamza Ali\n- Irum Saba"
    )


if __name__ == "__main__":
    main()
