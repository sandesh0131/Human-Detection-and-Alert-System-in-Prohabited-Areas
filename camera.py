import cv2
import face_recognition
import numpy as np
import os
import threading
import time
from datetime import datetime
import winsound
from twilio.rest import Client
from ultralytics import YOLO
import torch

# ==========================================
# 🛑 CONFIGURATION: ENTER YOUR KEYS HERE 🛑
# ==========================================
TWILIO_SID = "YOUR_TWILIO_SID_HERE"
TWILIO_AUTH_TOKEN = "YOUR_TWILIO_AUTH_TOKEN_HERE"
TWILIO_PHONE_NUMBER = "YOUR_TWILIO_PHONE_NUMBER"     
TARGET_PHONE_NUMBER = "YOUR_TARGET_PHONE_NUMBER"     

global_last_alert_time = 0
alert_lock = threading.Lock()

def trigger_full_alert():
    try:
        winsound.Beep(1500, 1500)
    except Exception:
        pass

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_body = f"SECURITY ALERT: Unauthorized person detected at {timestamp}!"

    if "YOUR_" not in TWILIO_SID:
        try:
            client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message_body,
                from_=TWILIO_PHONE_NUMBER,
                to=TARGET_PHONE_NUMBER
            )
            print(f"✅ Alert SMS sent to {TARGET_PHONE_NUMBER}")
        except Exception as e:
            print(f"❌ Failed to send SMS: {e}")

class VideoCamera(object):
    def __init__(self, camera_url, cam_id):
        self.cam_id = cam_id
        self.camera_url = camera_url
        self.video = None
        self.current_frame = None
        self.current_boxes = [] 
        self.stopped = False

        self.model = YOLO('yolov8n.pt')

        self.known_face_encodings = []
        self.known_face_names = []
        self.load_authorized_faces('static/authorized_faces/')
        
        self.alert_cooldown = 15.0 

        self.cam_thread = threading.Thread(target=self.update_camera_stream, daemon=True)
        self.cam_thread.start()

        self.ai_thread = threading.Thread(target=self.process_ai, daemon=True)
        self.ai_thread.start()

    def load_authorized_faces(self, path):
        # FIX: Create temporary lists so we don't clear the active database 
        # while the AI thread is busy reading from it!
        new_encodings = []
        new_names = []
        
        if not os.path.exists(path): return
            
        for filename in os.listdir(path):
            if filename.lower().endswith(('.jpg', '.png', '.jpeg')):
                img_path = os.path.join(path, filename)
                image = face_recognition.load_image_file(img_path)
                try:
                    encoding = face_recognition.face_encodings(image)[0]
                    new_encodings.append(encoding)
                    
                    display_name = filename.split('__')[0].replace('_', ' ').title()
                    new_names.append(display_name)
                except:
                    pass
        
        # Atomic Swap: Instantly replace the old lists with the new ones.
        # This is 100% thread-safe in Python.
        self.known_face_encodings = new_encodings
        self.known_face_names = new_names

    def update_camera_stream(self):
        self.video = cv2.VideoCapture(self.camera_url)
        self.video.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        while not self.stopped:
            success, frame = self.video.read()
            if success:
                height, width = frame.shape[:2]
                if width > 640:
                    scale = 640 / float(width)
                    frame = cv2.resize(frame, (640, int(height * scale)))
                self.current_frame = frame
                time.sleep(0.01) 
            else:
                time.sleep(0.03)

    def process_ai(self):
        global global_last_alert_time
        
        while not self.stopped:
            if self.current_frame is None:
                time.sleep(0.01)
                continue

            ai_image = self.current_frame.copy()
            temp_boxes = []

            with torch.no_grad():
                results = self.model(ai_image, classes=[0], conf=0.30, imgsz=640, verbose=False)
            
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].int().tolist()
                    person_crop = ai_image[max(0, y1):y2, max(0, x1):x2]
                    
                    if person_crop.size == 0: continue

                    rgb_frame = cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB)
                    face_locations = face_recognition.face_locations(rgb_frame, model="hog")
                    
                    if not face_locations:
                        name = "Suspicious: Face Obscured"
                        color = (0, 165, 255) 
                        trigger_alert = True
                    else:
                        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                        name = "Unauthorized Intruder"
                        color = (0, 0, 255) 
                        trigger_alert = True

                        for face_encoding in face_encodings:
                            matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=0.55)
                            face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)
                            if len(face_distances) > 0:
                                best_match_index = np.argmin(face_distances)
                                if matches[best_match_index]:
                                    name = f"Authorized: {self.known_face_names[best_match_index]}"
                                    color = (0, 255, 0) 
                                    trigger_alert = False 
                    
                    temp_boxes.append((x1, y1, x2, y2, name, color))
                    
                    if trigger_alert:
                        with alert_lock:
                            current_time = time.time()
                            if current_time - global_last_alert_time > self.alert_cooldown:
                                global_last_alert_time = current_time
                                
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                os.makedirs("static/logs", exist_ok=True) 
                                cv2.imwrite(f"static/logs/susp_log_cam{self.cam_id}_{timestamp}.jpg", ai_image)

                                threading.Thread(target=trigger_full_alert, daemon=True).start()

            self.current_boxes = temp_boxes
            time.sleep(0.02)

    def stop(self):
        self.stopped = True
        
        if hasattr(self, 'cam_thread') and self.cam_thread.is_alive():
            self.cam_thread.join(timeout=1.0)
            
        if hasattr(self, 'ai_thread') and self.ai_thread.is_alive():
            self.ai_thread.join(timeout=1.0)
            
        if self.video: 
            self.video.release()
            self.video = None

    def __del__(self):
        self.stop()

    def get_frame(self):
        if self.current_frame is None: 
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, f"CAM {self.cam_id} CONNECTING...", (100, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, jpeg = cv2.imencode('.jpg', placeholder)
            return jpeg.tobytes()
            
        display_image = self.current_frame.copy()
        cv2.putText(display_image, f"CAM {self.cam_id}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        for (x1, y1, x2, y2, name, color) in self.current_boxes:
            cv2.rectangle(display_image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_image, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        ret, jpeg = cv2.imencode('.jpg', display_image)
        return jpeg.tobytes()
