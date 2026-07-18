from flask import Flask, render_template, Response, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from camera import VideoCamera
import os
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/authorized_faces'

video_streams = {1: None, 2: None, 3: None, 4: None}

@app.route('/')
def index():
    active_cams = [cam_id for cam_id, cam in video_streams.items() if cam is not None]
    camera_active = len(active_cams) > 0
    return render_template('index.html', camera_active=camera_active, active_cams=active_cams)

def gen(camera):
    while True:
        if camera is None or camera.stopped:
            break
            
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
            
        # FIX: Always sleep slightly to cap the framerate (approx 20 FPS).
        # This prevents the server from flooding the socket and crashing!
        time.sleep(0.05)

@app.route('/video_feed/<int:cam_id>')
def video_feed(cam_id):
    global video_streams
    if video_streams.get(cam_id) is None:
        return "", 204
    return Response(gen(video_streams[cam_id]), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_camera', methods=['POST'])
def start_camera():
    global video_streams
    
    for i in range(1, 5):
        if video_streams[i] is not None:
            video_streams[i].stop() 
            video_streams[i] = None
    
    for i in range(1, 5):
        ip_address = request.form.get(f'camera_ip_{i}', '').strip()
        
        if ip_address:
            if not ip_address.startswith('http'):
                ip_address = f"http://{ip_address}"
            if ":4747" not in ip_address and "video" not in ip_address:
                ip_address = f"{ip_address}:4747/video"
            elif not ip_address.endswith("/video") and not ip_address.endswith("/mjpegfeed"):
                ip_address = f"{ip_address}/video"
                
            video_streams[i] = VideoCamera(ip_address, cam_id=i)
            
    return redirect(url_for('index'))

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global video_streams
    for i in range(1, 5):
        if video_streams[i] is not None:
            video_streams[i].stop()
            video_streams[i] = None
    return redirect(url_for('index'))

@app.route('/register_person', methods=['POST'])
def register_person():
    name = request.form.get('auth_name')
    emp_id = request.form.get('auth_id')
    files = request.files.getlist('auth_images')
    
    if name and emp_id and files:
        clean_name = secure_filename(name)
        clean_id = secure_filename(emp_id)
        
        for idx, file in enumerate(files):
            if file and file.filename != '':
                filename = f"{clean_name}__{clean_id}__{idx}.jpg"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        for cam in video_streams.values():
            if cam is not None:
                cam.load_authorized_faces(app.config['UPLOAD_FOLDER'])
                
    return redirect(url_for('index'))

@app.route('/get_data')
def get_data():
    log_dir = 'static/logs'
    logs = sorted(os.listdir(log_dir), reverse=True) if os.path.exists(log_dir) else []
    return jsonify({'logs': logs})

if __name__ == '__main__':
    os.makedirs('static/logs', exist_ok=True)
    os.makedirs('static/authorized_faces', exist_ok=True)
    
    # FIX: use_reloader=False and threaded=True prevents Flask from randomly 
    # stopping or crashing when multiple camera threads are running in the background.
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=False)
