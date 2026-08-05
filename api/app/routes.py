"""
Flask REST API Routes
Provides HTTP endpoints for reading violation data and live detection feed.
"""

from flask import Blueprint, request, jsonify, send_file, Response, render_template_string, stream_with_context
from datetime import datetime
from pathlib import Path
import os
import time

api_bp = Blueprint('api', __name__)

# Database instance will be set from main.py
db = None
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/outputs"))

LIVE_FEED_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Detection Feed</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0f;
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(90deg, #e74c3c, #f1c40f);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 20px;
            letter-spacing: 0.5px;
        }
        .status-bar {
            display: flex;
            gap: 24px;
            margin-bottom: 16px;
            font-size: 0.85rem;
            color: #888;
            align-items: center;
        }
        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: #2ecc71;
            display: inline-block;
            margin-right: 6px;
            animation: pulse 1.5s ease-in-out infinite;
        }
        .status-dot.offline { background: #e74c3c; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .feed-container {
            position: relative;
            border: 2px solid #333;
            border-radius: 12px;
            overflow: hidden;
            max-width: 1280px;
            width: 100%;
            background: #000;
            box-shadow: 0 0 50px rgba(231, 76, 60, 0.08);
            transition: border-color 0.3s;
        }
        .feed-container.live { border-color: #2ecc71; }
        .feed-container.offline { border-color: #e74c3c; }
        .feed-container img {
            width: 100%;
            height: auto;
            display: block;
        }
        .stream-info {
            margin-top: 14px;
            display: flex;
            gap: 16px;
            align-items: center;
            font-size: 0.8rem;
        }
        .stream-info .badge {
            background: #1a1a2e;
            padding: 4px 12px;
            border-radius: 6px;
            color: #888;
        }
        .stream-info .badge span { color: #f1c40f; }
        .controls {
            margin-top: 14px;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .controls button {
            background: #222;
            color: #ccc;
            border: 1px solid #444;
            padding: 7px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.2s;
        }
        .controls button:hover {
            background: #333;
            border-color: #e74c3c;
            color: white;
        }
        .controls button.danger:hover { border-color: #e74c3c; }
        .footer {
            margin-top: 24px;
            font-size: 0.7rem;
            color: #333;
        }
        .fps-counter {
            font-size: 0.8rem;
            color: #555;
            margin-left: auto;
        }
    </style>
</head>
<body>
    <h1>Live Detection Feed</h1>
    <div class="status-bar">
        <span><span class="status-dot" id="statusDot"></span>Stream: <span id="streamStatus" style="color:#2ecc71;font-weight:600;">LIVE</span></span>
        <span>Frames: <span id="frameCounter" style="color:#f1c40f;font-weight:600;">0</span></span>
        <span>Resolution: <span style="color:#888;">1280x720</span></span>
        <span>Mode: <span style="color:#2ecc71;font-weight:600;">MJPEG</span></span>
    </div>
    <div class="feed-container live" id="feedContainer">
        <img id="mjpegImage" src="/mjpeg" alt="Live MJPEG Stream" />
    </div>
    <div class="stream-info">
        <div class="badge">Format: <span>multipart/x-mixed-replace</span></div>
        <div class="badge">FPS: <span id="fpsDisplay">--</span></div>
        <div class="badge">Latency: <span id="latencyDisplay">--</span></div>
    </div>
    <div class="controls">
        <button onclick="location.reload()">🔄 Reconnect</button>
        <button onclick="window.open('/live', '_blank')">📺 Open in new tab</button>
    </div>
    <div class="footer">
        Traffic Violation Detection System &middot; MJPEG Stream
    </div>

    <script>
        const img = document.getElementById('mjpegImage');
        const statusDot = document.getElementById('statusDot');
        const streamStatus = document.getElementById('streamStatus');
        const frameCounter = document.getElementById('frameCounter');
        const fpsDisplay = document.getElementById('fpsDisplay');
        const latencyDisplay = document.getElementById('latencyDisplay');
        const container = document.getElementById('feedContainer');

        let frameCount = 0;
        let lastTimestamp = performance.now();
        let fpsValues = [];

        img.onload = function() {
            frameCount++;
            frameCounter.textContent = frameCount;

            // Calculate FPS
            const now = performance.now();
            const elapsed = (now - lastTimestamp) / 1000;
            if (elapsed > 0) {
                const fps = 1 / elapsed;
                fpsValues.push(fps);
                if (fpsValues.length > 30) fpsValues.shift();
                const avgFps = fpsValues.reduce((a, b) => a + b, 0) / fpsValues.length;
                fpsDisplay.textContent = avgFps.toFixed(1);
                latencyDisplay.textContent = (elapsed * 1000).toFixed(0) + 'ms';
            }
            lastTimestamp = now;

            statusDot.className = 'status-dot';
            streamStatus.textContent = 'LIVE';
            streamStatus.style.color = '#2ecc71';
            container.className = 'feed-container live';
        };

        img.onerror = function() {
            statusDot.className = 'status-dot offline';
            streamStatus.textContent = 'OFFLINE';
            streamStatus.style.color = '#e74c3c';
            container.className = 'feed-container offline';
            setTimeout(() => { img.src = '/mjpeg?_=' + Date.now(); }, 2000);
        };
    </script>
</body>
</html>
"""


def init_routes(database):
    """Initialize the database reference for routes"""
    global db
    db = database


@api_bp.route('/violations', methods=['GET'])
def get_violations():
    """
    List recorded violations
    ---
    tags:
      - Violations
    summary: List recorded violations
    description: >
      Returns violation records from the shared database, newest first,
      with optional filtering by violation type, license plate, or date range.
    parameters:
      - name: violation_type
        in: query
        type: string
        required: false
        description: >
          Filter by violation type. Known types: NO_HELMET, RED_LIGHT,
          OVER_SPEED, LANE_VIOLATION, ILLEGAL_UTURN.
      - name: license_plate
        in: query
        type: string
        required: false
        description: Filter by license plate text (case-sensitive).
      - name: start_date
        in: query
        type: string
        required: false
        description: >
          Only include violations at or after this value
          (YYYY-MM-DD or ISO-8601 datetime).
      - name: end_date
        in: query
        type: string
        required: false
        description: >
          Only include violations at or before this value
          (YYYY-MM-DD or ISO-8601 datetime).
      - name: limit
        in: query
        type: integer
        required: false
        default: 100
        description: Maximum number of records to return.
    responses:
      200:
        description: List of violation records.
        schema:
          type: object
          properties:
            count:
              type: integer
              description: Number of violations returned.
            violations:
              type: array
              description: Violation records.
              items:
                type: object
                properties:
                  id:
                    type: integer
                  violation_type:
                    type: string
                  timestamp:
                    type: string
                    format: date-time
                  location:
                    type: string
                  vehicle_type:
                    type: string
                  license_plate:
                    type: string
                  confidence:
                    type: number
                  speed:
                    type: number
                  speed_limit:
                    type: number
                  evidence_image_path:
                    type: string
                  video_frame_number:
                    type: integer
                  metadata:
                    type: object
                  created_at:
                    type: string
                    format: date-time
    """
    filters = {}
    
    violation_type = request.args.get('violation_type')
    if violation_type:
        filters['violation_type'] = violation_type
    
    license_plate = request.args.get('license_plate')
    if license_plate:
        filters['license_plate'] = license_plate
    
    start_date = request.args.get('start_date')
    if start_date:
        filters['start_date'] = start_date
    
    end_date = request.args.get('end_date')
    if end_date:
        filters['end_date'] = end_date
    
    limit = request.args.get('limit', 100, type=int)
    
    violations = db.get_violations(filters=filters, limit=limit)
    
    return jsonify({
        'count': len(violations),
        'violations': violations
    })


@api_bp.route('/violations/<int:violation_id>', methods=['GET'])
def get_violation(violation_id):
    """
    Get a single violation by ID
    ---
    tags:
      - Violations
    summary: Get a single violation by ID
    description: Returns the full record for one violation, or 404 if the ID does not exist.
    parameters:
      - name: violation_id
        in: path
        type: integer
        required: true
        description: Violation record ID.
    responses:
      200:
        description: The requested violation record.
        schema:
          type: object
          properties:
            id:
              type: integer
            violation_type:
              type: string
            timestamp:
              type: string
              format: date-time
            location:
              type: string
            vehicle_type:
              type: string
            license_plate:
              type: string
            confidence:
              type: number
            speed:
              type: number
            speed_limit:
              type: number
            evidence_image_path:
              type: string
            video_frame_number:
              type: integer
            metadata:
              type: object
            created_at:
              type: string
              format: date-time
      404:
        description: Violation not found.
        schema:
          type: object
          properties:
            error:
              type: string
              example: Violation not found
    """
    violation = db.get_violation_by_id(violation_id)
    
    if violation is None:
        return jsonify({'error': 'Violation not found'}), 404
    
    return jsonify(violation)


@api_bp.route('/statistics', methods=['GET'])
def get_statistics():
    """
    Get violation statistics
    ---
    tags:
      - Statistics
    summary: Get violation statistics
    description: >
      Aggregates violation counts grouped by violation type,
      optionally filtered by date range.
    parameters:
      - name: start_date
        in: query
        type: string
        required: false
        description: Only include statistics at or after this date (YYYY-MM-DD).
      - name: end_date
        in: query
        type: string
        required: false
        description: Only include statistics at or before this date (YYYY-MM-DD).
    responses:
      200:
        description: Violation counts by type.
        schema:
          type: object
          properties:
            statistics:
              type: object
              description: Map of violation type to total count.
              additionalProperties:
                type: integer
            total:
              type: integer
              description: Sum of all counts.
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    stats = db.get_statistics(
        start_date=start_date,
        end_date=end_date
    )
    
    return jsonify({
        'statistics': stats,
        'total': sum(stats.values()) if stats else 0
    })


@api_bp.route('/health', methods=['GET'])
def health():
    """
    Health check endpoint
    ---
    tags:
      - System
    summary: Health check
    description: >
      Verifies the API can read from the shared database. Used by the
      Docker healthcheck and load balancers.
    responses:
      200:
        description: API is healthy.
        schema:
          type: object
          properties:
            status:
              type: string
              enum: [healthy]
            database:
              type: string
              enum: [connected]
            violations_count:
              type: integer
              description: Total violations currently in the database.
      500:
        description: API is unhealthy (database unreachable).
        schema:
          type: object
          properties:
            status:
              type: string
              enum: [unhealthy]
            error:
              type: string
    """
    try:
        # Verify we can read from the database
        count = len(db.get_violations(limit=1))
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'violations_count': count
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@api_bp.route('/worker-status', methods=['GET'])
def worker_status():
    """
    Worker status and heartbeat
    ---
    tags:
      - System
    summary: Worker status and heartbeat
    description: >
      Reports whether the detection worker is actively processing by
      checking the age of the latest_frame.jpg heartbeat file that the
      worker writes to the shared outputs volume.
    responses:
      200:
        description: Current worker status.
        schema:
          type: object
          properties:
            status:
              type: string
              enum: [active, idle, offline]
              description: >
                active if a frame was written in the last 15s,
                idle if within 60s, offline otherwise.
            worker_heartbeat_age:
              type: number
              description: Seconds since the worker last wrote a frame (-1 if none yet).
            worker_heartbeat_time:
              type: string
              format: date-time
              description: Timestamp of the latest worker frame.
            violations_count:
              type: integer
            message:
              type: string
              description: Present when no heartbeat file exists.
    """
    latest = OUTPUT_DIR / "latest_frame.jpg"
    now = datetime.now()

    if latest.exists():
        mtime = datetime.fromtimestamp(latest.stat().st_mtime)
        age_sec = (now - mtime).total_seconds()

        if age_sec < 15:
            status = "active"
        elif age_sec < 60:
            status = "idle"
        else:
            status = "offline"

        violation_count = 0
        if db:
            try:
                violation_count = len(db.get_violations(limit=1))
            except Exception:
                pass

        return jsonify({
            'status': status,
            'worker_heartbeat_age': round(age_sec, 1),
            'worker_heartbeat_time': mtime.isoformat(),
            'violations_count': violation_count,
        })

    return jsonify({
        'status': 'offline',
        'worker_heartbeat_age': -1,
        'worker_heartbeat_time': None,
        'violations_count': 0,
        'message': 'No heartbeat from worker (latest_frame.jpg not found)'
    })


@api_bp.route('/live-feed', methods=['GET'])
def live_feed():
    """
    Latest annotated detection frame
    ---
    tags:
      - Live Feed
    summary: Latest annotated detection frame
    description: >
      Serves the most recent annotated frame saved by the worker
      (shared volume /app/outputs/latest_frame.jpg) as a JPEG image.
      Returns 204 No Content when no frame is available yet.
    produces:
      - image/jpeg
    responses:
      200:
        description: The latest annotated frame as a JPEG image.
      204:
        description: No frame available yet (worker not running).
    """
    latest = OUTPUT_DIR / "latest_frame.jpg"
    if latest.exists():
        return send_file(str(latest), mimetype='image/jpeg', max_age=0)
    # Return a placeholder 1x1 pixel if no feed yet
    return Response('', status=204, mimetype='image/jpeg')


@api_bp.route('/mjpeg', methods=['GET'])
def mjpeg_feed():
    """
    MJPEG video stream of detection frames
    ---
    tags:
      - Live Feed
    summary: MJPEG video stream
    description: >
      Streaming endpoint that pushes the latest annotated detection frames
      continuously using multipart/x-mixed-replace. Compatible with
      an <img> tag in HTML. Polls the shared outputs volume at ~30 fps.
    produces:
      - multipart/x-mixed-replace
    responses:
      200:
        description: Continuous MJPEG stream of annotated detection frames.
    """
    def generate():
        latest = OUTPUT_DIR / "latest_frame.jpg"
        last_mtime = 0

        while True:
            try:
                if latest.exists():
                    current_mtime = latest.stat().st_mtime_ns
                    if current_mtime != last_mtime:
                        last_mtime = current_mtime
                        with open(latest, 'rb') as f:
                            frame_data = f.read()
                        yield (
                            b'--jpgframe\r\n'
                            b'Content-Type: image/jpeg\r\n'
                            b'Content-Length: ' + str(len(frame_data)).encode() + b'\r\n'
                            b'\r\n'
                            + frame_data +
                            b'\r\n'
                        )
                else:
                    if last_mtime != -1:
                        last_mtime = -1
                    time.sleep(0.5)  # slow poll when no file
                    continue
                time.sleep(0.033)  # ~30 fps polling
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype='multipart/x-mixed-replace; boundary=--jpgframe',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    )


@api_bp.route('/live', methods=['GET'])
def live_page():
    """
    Live feed HTML viewer
    ---
    tags:
      - Live Feed
    summary: Live feed HTML viewer
    description: >
      Serves an HTML page with an embedded MJPEG stream viewer.
      Open in a browser at http://localhost:5001/live.
    produces:
      - text/html
    responses:
      200:
        description: HTML page with embedded live MJPEG stream.
    """
    return render_template_string(LIVE_FEED_HTML)
