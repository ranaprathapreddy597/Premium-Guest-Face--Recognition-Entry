"""
Premium Enterprise Biometric Kiosk Backend
Tech Stack: Python, DeepFace, FAISS, Flask-SQLAlchemy, SQLite
"""

import os
import json
import base64
import logging
import time
import uuid
import threading
import numpy as np
import cv2
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine
from models import db, User, AccessLog

# ─── Directories & Config ──────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("database/faces", exist_ok=True)
os.makedirs("instance", exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'visiongate-super-secret-key-for-showcase'
CORS(app)

# --- Rate Limiting (Security Hardening) ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    # Security Headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///visiongate.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 15, 'check_same_thread': False}}

# --- SQLite WAL Optimization ---
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

db.init_app(app)

CONFIG = {
    "RECOGNITION_THRESHOLD": 0.45,   
    "EMBED_MODEL": "ArcFace",         
    "VERIFY_DETECTOR": "opencv",      # More robust detector for backend verification
    "FACES_DIR": "database/faces",
    "GATE_OPEN_DURATION": 4,
    "SMTP_USER": "your_email@gmail.com",  # Replace with actual email
    "SMTP_PASS": "your_app_password_here" # Replace with actual App Password
}

# ─── System State ─────────────────────────────────────────────────────────────
system_state = {
    "gate_status": "CLOSED",
    "last_recognition": None,
    "last_emotion": "neutral",
    "agent_actions": []
}

# ─── AI Engine (DeepFace + FAISS) ──────────────────────────────────────────────
AI_AVAILABLE = False
faiss_index = None
faiss_id_map = {}

def build_faiss_index():
    global faiss_index, faiss_id_map
    import faiss
    faiss_index = faiss.IndexFlatIP(512) 
    faiss_id_map.clear()
    
    with app.app_context():
        approved_users = User.query.filter_by(status='APPROVED', has_biometrics=True).all()
        idx = 0
        for u in approved_users:
            if u.embedding_json:
                emb_list = json.loads(u.embedding_json)
                emb_np = np.array([emb_list], dtype=np.float32)
                faiss.normalize_L2(emb_np)
                faiss_index.add(emb_np)
                faiss_id_map[idx] = u.id
                idx += 1
        logger.info(f"✅ FAISS Index rebuilt. {idx} active vectors loaded into RAM.")

try:
    from deepface import DeepFace
    import faiss
    AI_AVAILABLE = True
except ImportError:
    logger.error("❌ DeepFace or FAISS not installed.")

# ─── Database Initialization ───────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        if User.query.count() == 0:
            logger.info("Initializing mock data into SQLite...")
            colors = ['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98D8C8']
            u1 = User(id="M001", name="Arjun Sharma", tier="PLATINUM", airline="Air India", ff_number="AI-9872341", pref_drink="Masala Chai", pref_seat="Window", avatar_initials="AS", avatar_color="#6C63FF", status="APPROVED")
            # We don't have embeddings for mock data initially, they will be text-only until enrolled
            db.session.add(u1)
            db.session.commit()
        if AI_AVAILABLE:
            build_faiss_index()

# ─── Helper Functions ──────────────────────────────────────────────────────────
def generate_agent_actions(user_dict, emotion, is_delayed):
    actions = []
    if emotion in ['angry', 'sad', 'fear']:
        actions.append(f"🚨 ALERT: {user_dict['name']} appears stressed — deploy service recovery")
    
    actions.append(f"☕ Prepare {user_dict['preferences']['drink']} for {user_dict['name'].split()[0]}")
    
    if is_delayed:
        actions.append(f"✈️ Flight to DEL is Delayed — Auto-extending lounge access.")
        actions.append(f"🍽️ Hold pre-flight meal — guest has extended stay")
    else:
        actions.append(f"✈️ Flight to DEL is On Time — Boarding in 45 mins.")
            
    actions.append(f"🛋️ Adjusting suite climate to {user_dict['name'].split()[0]}'s saved preferences")
    
    # Simulate Agentic web-hook/Slack ping
    logger.info(f"🤖 [AGENTIC CONCIERGE API PUSH] -> Slack Channel #lounge-staff: VIP {user_dict['name']} ({user_dict['tier']}) just entered. Prepare {user_dict['preferences']['drink']}.")
    return actions

def send_real_email(to_email, name, status):
    """Sends an actual SMTP email to the user regarding their enrollment status."""
    if not to_email: return
    
    logger.info("=" * 60)
    logger.info(f"📧 [EMAIL NOTIFICATION TRIGGERED] To: {to_email} | Status: {status}")
    
    if CONFIG.get("SMTP_USER") == "your_email@gmail.com" or not CONFIG.get("SMTP_PASS"):
        logger.warning("SMTP Config missing. Replace your_email@gmail.com and password in CONFIG to send real emails.")
        logger.info("=" * 60)
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = CONFIG["SMTP_USER"]
        msg['To'] = to_email
        msg['Subject'] = f"VisionGate Smart Lounge: Profile {status}"
        
        body = f"Hello {name},\n\nYour biometric lounge profile has been {status}.\n\nThank you,\nVisionGate Security"
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(CONFIG["SMTP_USER"], CONFIG["SMTP_PASS"])
        server.send_message(msg)
        server.quit()
        logger.info(f"✅ Real email successfully sent to {to_email}")
    except Exception as e:
        logger.error(f"❌ Failed to send email: {str(e)}")
    logger.info("=" * 60)

def log_access(user, status, conf, emotion="neutral"):
    with app.app_context():
        log = AccessLog(
            user_id=user.id if user else None,
            user_name=user.name if user else "Unknown Subject",
            event_type=status,
            confidence=conf,
            emotion=emotion
        )
        db.session.add(log)
        db.session.commit()
        
        user_dict = user.to_dict() if user else None

        if status == "GRANTED" and user_dict: 
            system_state["last_recognition"] = user_dict
            system_state["last_emotion"] = emotion
            is_delayed = np.random.choice([True, False], p=[0.2, 0.8])
            system_state["agent_actions"] = generate_agent_actions(user_dict, emotion, is_delayed)
            
        return log.to_dict()

def open_gate_sequence():
    system_state["gate_status"] = "OPEN"
    def close_gate():
        time.sleep(CONFIG["GATE_OPEN_DURATION"])
        system_state["gate_status"] = "CLOSED"
        system_state["last_recognition"] = None
        system_state["agent_actions"] = []
    threading.Thread(target=close_gate).start()

def alert_gate_sequence():
    system_state["gate_status"] = "ALERT"
    def close_gate():
        time.sleep(4)
        system_state["gate_status"] = "CLOSED"
    threading.Thread(target=close_gate).start()

# ─── Security Decorators ───────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ─── API Endpoints (HTML Portals) ─────────────────────────────────────────────
@app.route('/')
def kiosk_redirect(): 
    return render_template('kiosk.html')

@app.route('/enroll')
def enroll_portal(): 
    return render_template('enroll.html')

@app.route('/admin')
@login_required
def admin_portal(): 
    return render_template('admin.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == 'admin' and request.form.get('password') == 'password':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_portal'))
        return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# ─── API Endpoints (Core Logic) ────────────────────────────────────────────────
@app.route('/api/state')
def get_state():
    with app.app_context():
        total_today = AccessLog.query.filter_by(event_type='GRANTED').count()
        spoofs_today = AccessLog.query.filter(AccessLog.event_type.in_(['SPOOF_DETECTED', 'DENIED'])).count()
        recent_logs = [log.to_dict() for log in AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(20).all()]
        active_members = User.query.filter_by(status='APPROVED').count()

        safe_member = system_state["last_recognition"].copy() if system_state["last_recognition"] else None
            
        return jsonify({
            "total_today": total_today,
            "spoofs_today": spoofs_today,
            "access_log": recent_logs,
            "active_members": active_members,
            "gate_status": system_state["gate_status"],
            "last_recognition": safe_member,
            "last_emotion": system_state["last_emotion"],
            "agent_actions": system_state["agent_actions"]
        })

@app.route('/api/admin/users')
def get_users():
    if 'admin_logged_in' not in session: return jsonify({"error": "Unauthorized"}), 401
    status_filter = request.args.get('status')
    with app.app_context():
        query = User.query
        if status_filter:
            query = query.filter_by(status=status_filter)
        users = [u.to_dict() for u in query.order_by(User.created_at.desc()).all()]
        return jsonify(users)

@app.route('/api/admin/users/<user_id>/status', methods=['POST'])
def update_user_status(user_id):
    if 'admin_logged_in' not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    new_status = data.get('status') # APPROVED, REJECTED, REVOKED
    with app.app_context():
        user = User.query.get(user_id)
        if not user: return jsonify({"success": False, "message": "User not found"})
        
        user.status = new_status
        db.session.commit()
        
        if new_status == 'APPROVED':
            log_access(user, "ENROLLED", 1.0)
            send_real_email(user.email, user.name, "APPROVED")
        elif new_status == 'REVOKED':
            log_access(user, "REVOKED", 1.0)
            send_real_email(user.email, user.name, "REVOKED")
        elif new_status == 'REJECTED':
            send_real_email(user.email, user.name, "REJECTED")
            
        # Rebuild FAISS index to reflect change immediately in RAM
        build_faiss_index()
        return jsonify({"success": True})

@app.route('/api/enroll', methods=['POST'])
@limiter.limit("10 per minute") # Rate limiting enrollment to prevent bot abuse
def enroll_user():
    data = request.json
    user_id = f"M{str(uuid.uuid4())[:6].upper()}"
    colors = ['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98D8C8']
    
    avatar_init = "".join([n[0] for n in data["name"].split()[:2]]).upper()
    
    # Process Biometrics if available
    embedding_json = None
    has_bio = False
    if "image_b64" in data and data["image_b64"]:
        try:
            img_data = base64.b64decode(data["image_b64"].split(',')[1])
            img_path = f"{CONFIG['FACES_DIR']}/{user_id}.jpg"
            with open(img_path, 'wb') as f: f.write(img_data)
            
            # --- Face Quality Assessment (FQA) ---
            # Check image sharpness/blurriness using Variance of Laplacian
            cv_img = cv2.imread(img_path)
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            fm = cv2.Laplacian(gray, cv2.CV_64F).var()
            if fm < 50.0:  # Threshold for blurriness
                if os.path.exists(img_path): os.remove(img_path)
                return jsonify({"success": False, "message": "Captured image is too blurry. Please ensure good lighting and hold still."})
            # --------------------------------------
            
            # Basic crop check at enrollment time
            faces = DeepFace.extract_faces(img_path=img_path, detector_backend=CONFIG["VERIFY_DETECTOR"], enforce_detection=True)
            
            emb = DeepFace.represent(img_path=img_path, model_name=CONFIG["EMBED_MODEL"], detector_backend=CONFIG["VERIFY_DETECTOR"], enforce_detection=True)[0]["embedding"]
            
            # --- Anti-Duplication Check ---
            emb_np = np.array([emb], dtype=np.float32)
            faiss.normalize_L2(emb_np)
            
            with app.app_context():
                for existing_u in User.query.filter_by(has_biometrics=True).all():
                    if existing_u.embedding_json:
                        ex_emb = np.array([json.loads(existing_u.embedding_json)], dtype=np.float32)
                        faiss.normalize_L2(ex_emb)
                        distance = 1 - np.dot(emb_np[0], ex_emb[0])
                        if distance <= CONFIG["RECOGNITION_THRESHOLD"]:
                            if os.path.exists(img_path): os.remove(img_path)
                            return jsonify({"success": False, "message": f"Biometrics already registered to user: {existing_u.name}"})
            # ------------------------------
            
            # --- DPDP Data Minimization ---
            # Instantly delete the raw JPEG image after the FAISS vector is extracted to comply with DPDP
            if os.path.exists(img_path):
                os.remove(img_path)
                logger.info(f"🛡️ DPDP Act 2023 Compliance: Raw image {img_path} permanently deleted after vector extraction.")
            # ------------------------------
            
            embedding_json = json.dumps(emb)
            has_bio = True
        except ValueError as e:
            logger.error(f"Enrollment detection error: {e}")
            if os.path.exists(img_path): os.remove(img_path)
            return jsonify({"success": False, "message": "No face detected in photo. Please ensure face is well-lit and centered."})
        except Exception as e: return jsonify({"success": False, "message": str(e)})

    with app.app_context():
        u = User(
            id=user_id, name=data["name"], email=data.get("email", ""), tier=data.get("tier", "SILVER"),
            airline=data.get("airline", ""), ff_number=data.get("ff", ""),
            pref_drink=data.get("drink", "Water"), pref_seat=data.get("seat", "Any"),
            avatar_initials=avatar_init, avatar_color=np.random.choice(colors),
            embedding_json=embedding_json, has_biometrics=has_bio, status="PENDING"
        )
        db.session.add(u)
        db.session.commit()
        return jsonify({"success": True, "message": "Enrollment submitted for Review."})

@app.route('/api/verify', methods=['POST'])
@limiter.limit("60 per minute") # Rate limiting verification (1 request per second max per client)
def verify_identity():
    """High accuracy backend verification. Designed to take face CROPS from MediaPipe frontend for zero-latency networking."""
    if not AI_AVAILABLE: return jsonify({"error": "AI Offline"})
    try:
        data = request.json
        num_faces = data.get("num_faces", 1)
        
        # Priority 1: Anti-Tailgating logic. Wait, if more than 1 face, prevent gate action entirely.
        if num_faces > 1:
            log_access(None, "TAILGATING", 0.0, "neutral")
            alert_gate_sequence()
            logger.warning("🚨 TAILGATING PREVENTED: Multiple faces in frame!")
            return jsonify({"success": True, "match": False, "message": "Tailgating Detected! Multiple faces in frame.", "is_tailgating": True})
            
        img_data = base64.b64decode(data["image_b64"].split(',')[1])
        temp_path = "database/temp_verify.jpg"
        with open(temp_path, 'wb') as f: f.write(img_data)
        
        # Strict detector for verification with Anti-Spoofing
        try:
            faces = DeepFace.extract_faces(img_path=temp_path, detector_backend=CONFIG["VERIFY_DETECTOR"], enforce_detection=False, anti_spoofing=True)
            if len(faces) > 0 and not faces[0].get("is_real", True):
                log_access(None, "SPOOF_DETECTED", 0.99, "angry")
                alert_gate_sequence()
                return jsonify({"success": True, "match": False, "message": "Spoof / Presentation Attack Detected", "is_real": False})
        except Exception as e:
            logger.warning(f"Spoof check failed or unsupported: {e}")
            pass

        # HIGH PERFORMANCE TWEAK: Since MediaPipe frontend already passes a perfect face crop,
        # we can bypass DeepFace's internal 2nd re-detection and instantly generate the embedding!
        emb = DeepFace.represent(img_path=temp_path, model_name=CONFIG["EMBED_MODEL"], detector_backend="skip", enforce_detection=False)[0]["embedding"]
        emb_np = np.array([emb], dtype=np.float32)
        faiss.normalize_L2(emb_np)
        
        if faiss_index and faiss_index.ntotal > 0:
            distances, indices = faiss_index.search(emb_np, 1)
            distance = 1 - distances[0][0]
            if distance <= CONFIG["RECOGNITION_THRESHOLD"]:
                with app.app_context():
                    user = User.query.get(faiss_id_map.get(indices[0][0]))
                    if user and user.status == 'APPROVED':
                        emotion = "neutral"
                        try:
                            emotion = DeepFace.analyze(img_path=temp_path, actions=["emotion"], enforce_detection=False, silent=True)[0]["dominant_emotion"]
                        except: pass
                        
                        log_access(user, "GRANTED", float(1 - distance), emotion)
                        open_gate_sequence()
                        return jsonify({"success": True, "match": True, "name": user.name, "confidence": float(1 - distance)})
                
        # Denied
        log_access(None, "DENIED", 0, "neutral")
        return jsonify({"success": True, "match": False, "message": "Identity not found or not approved."})
    except Exception as e: 
        logger.error(f"Verify error: {str(e)}")
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, threaded=False)