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

# CONFIGURATION: ENTER YOUR KEYS HERE

TWILIO_SID = "YOUR_TWILIO_SID_HERE"
TWILIO_AUTH_TOKEN = "YOUR_TWILIO_AUTH_TOKEN_HERE"
TWILIO_PHONE_NUMBER = "YOUR_TWILIO_PHONE_NUMBER"     # e.g., +12345678901
TARGET_PHONE_NUMBER = "YOUR_TARGET_PHONE_NUMBER"     # e.g., +919876543210

# Initialize YOLOv8 nano model
model = YOLO('yolov8n.pt')

def trigger_full_alert():
    """Runs Audio Alarm and SMS alerts in the background."""
    # 1. Audio Alarm (High-pitched beep for 1.5 seconds)
    try:
        winsound.Beep(1500, 1500)
    except Exception:
        pass

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_body = f"SECURITY ALERT: Unauthorized person detected at {timestamp}!"

    # 2. SMS Alert
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
    def __init__(self, camera_url=0):
        self.video = cv2.VideoCapture(camera_url)
        self.video.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.current_frame = None
        self.current_boxes = [] 
        self.stopped = False

        self.known_face_encodings = []
        self.known_face_names = []
        self.load_authorized_faces('static/authorized_faces/')
        
        self.last_alert_time = 0 
        self.alert_cooldown = 15.0 # 15s cooldown to prevent sms spam

        self.cam_thread = threading.Thread(target=self.update_camera_stream, daemon=True)
        self.cam_thread.start()

        self.ai_thread = threading.Thread(target=self.process_ai, daemon=True)
        self.ai_thread.start()

    def load_authorized_faces(self, path):
        self.known_face_encodings.clear()
        self.known_face_names.clear()
        
        if not os.path.exists(path): 
            return
            
        for filename in os.listdir(path):
            if filename.lower().endswith(('.jpg', '.png', '.jpeg')):
                img_path = os.path.join(path, filename)
                image = face_recognition.load_image_file(img_path)
                try:
                    encoding = face_recognition.face_encodings(image)[0]
                    self.known_face_encodings.append(encoding)
                    self.known_face_names.append(os.path.splitext(filename)[0].replace('_', ' ').title())
                except:
                    pass

    def update_camera_stream(self):
        while not self.stopped:
            success, frame = self.video.read()
            if success:
                # Cap raw stream width at 640px to reduce UI rendering overhead
                height, width = frame.shape[:2]
                if width > 640:
                    scale = 640 / float(width)
                    frame = cv2.resize(frame, (640, int(height * scale)))
                self.current_frame = frame

    def process_ai(self):
        while not self.stopped:
            if self.current_frame is None:
                time.sleep(0.01)
                continue

            ai_image = self.current_frame.copy()
            temp_boxes = []

            # Process at half resolution (imgsz=320) to force faster CPU inference
            results = model(ai_image, classes=[0], conf=0.5, imgsz=320, verbose=False)
            
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].int().tolist()
                    person_crop = ai_image[max(0, y1):y2, max(0, x1):x2]
                    
                    if person_crop.size == 0: continue

                    # Downscale face crop by 50% for faster recognition matching
                    small_crop = cv2.resize(person_crop, (0, 0), fx=0.5, fy=0.5)
                    rgb_small_frame = cv2.cvtColor(small_crop, cv2.COLOR_BGR2RGB)
                    
                    face_locations = face_recognition.face_locations(rgb_small_frame, model="hog")
                    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

                    name = "Unauthorized - Suspicious"
                    color = (0, 0, 255) 

                    for face_encoding in face_encodings:
                        matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=0.55)
                        face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)
                        if len(face_distances) > 0:
                            best_match_index = np.argmin(face_distances)
                            if matches[best_match_index]:
                                name = f"Authorized: {self.known_face_names[best_match_index]}"
                                color = (0, 255, 0) 
                    
                    temp_boxes.append((x1, y1, x2, y2, name, color))
                    
                    # --- ALERT SYSTEM EXECUTOR ---
                    if "Unauthorized" in name:
                        current_time = time.time()
                        if current_time - self.last_alert_time > self.alert_cooldown:
                            self.last_alert_time = current_time
                            
                            # Log the image
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            os.makedirs("static/logs", exist_ok=True) # <-- Fixed os.makedirs here!
                            cv2.imwrite(f"static/logs/susp_log_{timestamp}.jpg", ai_image)

                            # Fire off the voice and SMS in a background thread
                            threading.Thread(target=trigger_full_alert, daemon=True).start()

            self.current_boxes = temp_boxes

    def __del__(self):
        self.stopped = True 
        if hasattr(self, 'cam_thread'): self.cam_thread.join()
        if hasattr(self, 'ai_thread'): self.ai_thread.join()
        self.video.release()

    def get_frame(self):
        if self.current_frame is None: return None
        display_image = self.current_frame.copy()
        for (x1, y1, x2, y2, name, color) in self.current_boxes:
            cv2.rectangle(display_image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_image, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        ret, jpeg = cv2.imencode('.jpg', display_image)
        return jpeg.tobytes()