from flask import Flask, render_template, Response, request, redirect, url_for, jsonify
from camera import VideoCamera
import os
import time

app = Flask(__name__)

# Global state variable
video_stream = None

@app.route('/')
def index():
    """Renders the main dashboard."""
    camera_active = video_stream is not None
    return render_template('index.html', camera_active=camera_active)

def gen(camera):
    """Video streaming generator function with network buffering."""
    while True:
        if camera is None:
            break
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
        else:
            # Prevents server CPU thrashing if a frame is dropped
            time.sleep(0.1)

@app.route('/video_feed')
def video_feed():
    """Route for the live video feed."""
    global video_stream
    if video_stream is None:
        return "", 204
    return Response(gen(video_stream), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    """Starts the camera based on user selection."""
    global video_stream
    cam_type = request.form.get('cam_type')
    
    if video_stream is not None:
        del video_stream 
        video_stream = None
        
    if cam_type == 'webcam':
        video_stream = VideoCamera(0) 
    else:
        ip_address = request.form.get('camera_ip', '').strip()
        
        # Ensure IP string handles missing http:// or endpoint paths
        if not ip_address.startswith('http'):
            ip_address = f"http://{ip_address}"
        if ":4747" not in ip_address and "video" not in ip_address:
            ip_address = f"{ip_address}:4747/video"
        elif not ip_address.endswith("/video") and not ip_address.endswith("/mjpegfeed"):
            ip_address = f"{ip_address}/video"
            
        video_stream = VideoCamera(ip_address)
            
    return redirect(url_for('index'))

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    """Stops the current camera stream."""
    global video_stream
    if video_stream:
        del video_stream
        video_stream = None
    return redirect(url_for('index'))

@app.route('/get_data')
def get_data():
    """API endpoint to fetch latest logs dynamically."""
    log_dir = 'static/logs'
    logs = sorted(os.listdir(log_dir), reverse=True) if os.path.exists(log_dir) else []
    return jsonify({
        'logs': logs
    })

if __name__ == '__main__':
    # Ensure necessary directories exist on startup
    os.makedirs('static/logs', exist_ok=True)
    os.makedirs('static/authorized_faces', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)