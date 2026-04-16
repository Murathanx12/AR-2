"""Phone app — lightweight web server for voice control via phone browser.

Architecture:
  Phone browser (Web Speech API) → HTTP POST /command → Pi Flask → FSM

The phone's built-in STT is far more accurate than VOSK and the phone's mic
has hardware noise cancellation. This solves both the accuracy and mic problems.

Resource usage: ~20MB RAM, single thread, no database. Negligible on Pi 5.

Can also be hosted on a laptop — just change the PI_URL in the HTML.
"""

import threading
import logging
import json
import time

logger = logging.getLogger(__name__)

try:
    from flask import Flask, request, jsonify, render_template_string
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

# The full HTML page served to the phone browser
_HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>SONNY Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;display:grid;
grid-template-columns:1fr 340px;grid-template-rows:50px 1fr 180px;gap:6px;padding:6px;overflow:hidden}
.header{grid-column:span 2;background:#161b22;border-radius:8px;display:flex;align-items:center;padding:0 16px;gap:16px}
.header h1{color:#58a6ff;font-size:24px}
.state{background:#1f6feb;color:white;padding:4px 14px;border-radius:12px;font-size:16px;font-weight:bold}
.voice-text{flex:1;color:#8b949e;font-size:14px;text-align:right;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.cam-panel{background:#161b22;border-radius:8px;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center}
.cam-panel img{width:100%;height:100%;object-fit:contain}
.cam-panel .no-feed{color:#484f58;font-size:18px}
.sidebar{background:#161b22;border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:6px;overflow-y:auto}
.card{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:8px 10px}
.card .label{font-size:11px;color:#8b949e;margin-bottom:4px}
.ir-row{display:flex;gap:4px;justify-content:center}
.ir-dot{width:36px;height:24px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:bold}
.ir-on{background:#238636;color:white}
.ir-off{background:#21262d;color:#484f58}
.motor-row{font-family:monospace;font-size:14px;color:#79c0ff}
.bottom{grid-column:span 2;background:#161b22;border-radius:8px;display:grid;grid-template-columns:auto 1fr;gap:6px;padding:8px}
.btns{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
.btn{padding:10px 4px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9;font-size:13px;
cursor:pointer;text-align:center}
.btn:active{background:#1f6feb;color:white}
.btn.stop{background:#f8514922;border-color:#f85149;color:#f85149;font-size:16px;font-weight:bold}
.btn.stop:active{background:#f85149;color:white}
.mic-area{display:flex;flex-direction:column;align-items:center;gap:4px;justify-content:center}
.mic-btn{width:64px;height:64px;border-radius:50%;border:2px solid #30363d;background:#0d1117;color:#58a6ff;
font-size:28px;cursor:pointer}
.mic-btn.on{background:#1f6feb;color:white;border-color:#58a6ff;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(88,166,255,.4)}50%{box-shadow:0 0 0 12px rgba(88,166,255,0)}}
.log{font-size:11px;color:#484f58;max-height:60px;overflow-y:auto}
.log div{padding:1px 0}
.heard{color:#58a6ff;font-size:13px}
.intent-display{color:#3fb950;font-size:13px}
</style>
</head>
<body>

<div class="header">
<h1>SONNY</h1>
<span class="state" id="state">IDLE</span>
<span class="voice-text"><span class="heard" id="heard"></span> <span class="intent-display" id="intentD"></span></span>
</div>

<div class="cam-panel">
<img id="camFeed" src="/video_feed" onerror="this.style.display='none';document.getElementById('noFeed').style.display='block'">
<span class="no-feed" id="noFeed" style="display:none">No Camera Feed</span>
</div>

<div class="sidebar">
<div class="card"><div class="label">IR SENSORS</div>
<div class="ir-row" id="irRow">
<div class="ir-dot ir-off">W</div><div class="ir-dot ir-off">NW</div><div class="ir-dot ir-off">N</div>
<div class="ir-dot ir-off">NE</div><div class="ir-dot ir-off">E</div>
</div></div>
<div class="card"><div class="label">ULTRASONIC</div><div id="dist" style="font-size:18px;color:#79c0ff">---</div></div>
<div class="card"><div class="label">MOVEMENT</div><div class="motor-row" id="motor">vx:0 vy:0 w:0</div></div>
<div class="card"><div class="label">DETECTION</div><div id="detect" style="font-size:13px">Faces:0</div></div>
<div class="card"><div class="label">LOG</div><div class="log" id="log"></div></div>
</div>

<div class="bottom">
<div class="mic-area">
<button class="mic-btn" id="micBtn" onclick="toggleMic()">&#127908;</button>
<span style="font-size:11px;color:#8b949e" id="micStatus">Tap to speak</span>
</div>
<div class="btns">
<button class="btn" onclick="sendCmd('hello sonny')">Wake Up</button>
<button class="btn" onclick="sendCmd('follow track')">Follow Track</button>
<button class="btn" onclick="sendCmd('follow the marker')">Follow Marker</button>
<button class="btn" onclick="sendCmd('go to marker 8')">Marker 8</button>
<button class="btn" onclick="sendCmd('dance')">Dance</button>
<button class="btn" onclick="sendCmd('patrol')">Patrol</button>
<button class="btn" onclick="sendCmd('photo')">Photo</button>
<button class="btn" onclick="sendCmd('come here')">Come Here</button>
<button class="btn" onclick="sendCmd('sleep')">Sleep</button>
<button class="btn stop" onclick="sendCmd('stop')">STOP</button>
</div>
</div>

<script>
const API=window.location.origin;
let recognition=null,listening=false;

if('webkitSpeechRecognition' in window||'SpeechRecognition' in window){
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
recognition=new SR();recognition.continuous=false;recognition.interimResults=false;recognition.lang='en-US';
recognition.onresult=e=>{sendCmd(e.results[0][0].transcript);stopMic()};
recognition.onerror=()=>stopMic();recognition.onend=()=>stopMic()}

function toggleMic(){listening?stopMic():startMic()}
function startMic(){if(!recognition)return;listening=true;document.getElementById('micBtn').classList.add('on');
document.getElementById('micStatus').textContent='Listening...';recognition.start()}
function stopMic(){listening=false;document.getElementById('micBtn').classList.remove('on');
document.getElementById('micStatus').textContent='Tap to speak';try{recognition.stop()}catch(e){}}

function sendCmd(text){
document.getElementById('heard').textContent='"'+text+'"';
document.getElementById('intentD').textContent='sending...';
addLog('> '+text);
fetch(API+'/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})})
.then(r=>r.json()).then(d=>{document.getElementById('intentD').textContent=d.intent+' ('+d.confidence+')';addLog('= '+d.intent)})
.catch(e=>{document.getElementById('intentD').textContent='error';addLog('! '+e.message)})}

function addLog(m){const l=document.getElementById('log');
l.innerHTML='<div>'+new Date().toLocaleTimeString().slice(0,8)+' '+m+'</div>'+l.innerHTML;
if(l.children.length>8)l.removeChild(l.lastChild)}

// Auto-refresh status every 500ms
setInterval(()=>{
fetch(API+'/status').then(r=>r.json()).then(d=>{
document.getElementById('state').textContent=d.state;
const names=['W','NW','N','NE','E'];
const row=document.getElementById('irRow');
row.innerHTML=d.ir.map((v,i)=>'<div class="ir-dot '+(v?'ir-on':'ir-off')+'">'+names[i]+'</div>').join('');
document.getElementById('dist').textContent=d.dist>0?d.dist+'cm':'---';
document.getElementById('dist').style.color=d.dist>0&&d.dist<20?'#f85149':'#79c0ff';
document.getElementById('motor').textContent='vx:'+d.vx+' vy:'+d.vy+' w:'+d.omega;
document.getElementById('detect').textContent='Faces:'+d.faces+(d.voice?' | Voice: "'+d.voice+'"':'');
if(d.voice)document.getElementById('heard').textContent='"'+d.voice+'"';
}).catch(()=>{})},500);
</script>
</body>
</html>
"""


class WebController:
    """Lightweight Flask web server for phone-based voice control.

    Serves an HTML page with:
    - Mic button (uses phone's Web Speech API for STT)
    - Quick command buttons (tap to send without speaking)
    - Live feedback (intent, response)
    """

    def __init__(self, fsm=None, host="0.0.0.0", port=8080):
        """
        Args:
            fsm: AlfredFSM instance.
            host: Bind address. 0.0.0.0 = accessible from any device on network.
            port: Port number. Access via http://<pi-ip>:8080
        """
        self.fsm = fsm
        self.host = host
        self.port = port
        self._thread = None
        self._app = None

    def start(self):
        """Start web server in background thread."""
        if not _HAS_FLASK:
            print("[Web] Flask not installed. Run: pip install flask")
            return

        self._app = Flask(__name__)
        self._app.logger.setLevel(logging.WARNING)  # silence Flask logs

        @self._app.route("/")
        def index():
            return render_template_string(_HTML_PAGE)

        @self._app.route("/command", methods=["POST"])
        def command():
            data = request.get_json(silent=True) or {}
            text = data.get("text", "").strip()
            if not text:
                return jsonify({"error": "No text provided"}), 400

            intent = "unknown"
            confidence = "0%"
            response = ""

            # Classify and execute
            if self.fsm and self.fsm.intent_classifier:
                intent_name, conf = self.fsm.intent_classifier.classify(text)
                intent = intent_name
                confidence = f"{conf:.0%}"

                # Feed to FSM as if it came from the mic
                self.fsm._on_voice_command(text)

                # Also wake up if needed
                if self.fsm.voice_listener and not self.fsm.voice_listener.is_awake:
                    from alfred.voice.listener import WAKE_VARIANTS
                    for wake in WAKE_VARIANTS:
                        if wake in text.lower():
                            self.fsm.voice_listener._do_wake(
                                text.lower().split(wake, 1)[-1].strip()
                            )
                            break

                response = f"Executing: {intent}"

            return jsonify({
                "intent": intent,
                "confidence": confidence,
                "response": response,
                "text": text,
            })

        @self._app.route("/status")
        def status():
            """Return full robot state for live dashboard."""
            from alfred.fsm.states import STATE_NAMES
            state = "IDLE"
            ir_bits = [0,0,0,0,0]
            dist = -1
            vx = vy = omega = 0
            faces = 0
            last_voice = ""
            markers = []

            if self.fsm:
                state = STATE_NAMES.get(self.fsm.state, "?")
                if self.fsm.uart and self.fsm.uart.is_open:
                    ir_bits = self.fsm.uart.get_ir_bits()
                    dist = self.fsm.uart.get_distance()
                lf = self.fsm.line_follower
                if lf:
                    vx = lf.debug_vx
                    vy = lf.debug_vy
                    omega = lf.debug_omega
                faces = len(self.fsm._last_faces) if self.fsm._last_faces else 0
                if self.fsm.voice_listener:
                    last_voice = self.fsm.voice_listener.last_text

            return jsonify({
                "state": state,
                "ir": ir_bits,
                "dist": round(dist, 1),
                "vx": vx, "vy": vy, "omega": omega,
                "faces": faces,
                "voice": last_voice,
                "markers": markers,
            })

        @self._app.route("/video_feed")
        def video_feed():
            """MJPEG stream of camera with detection overlays."""
            from flask import Response
            def generate():
                while True:
                    if not self.fsm or not self.fsm.camera:
                        time.sleep(0.1)
                        continue
                    frame = self.fsm._last_frame
                    if frame is None:
                        time.sleep(0.05)
                        continue
                    try:
                        import cv2
                        display = frame.copy()
                        # Draw faces
                        if self.fsm._last_faces:
                            for face in self.fsm._last_faces:
                                x,y,w,h = face["bbox"]
                                cv2.rectangle(display,(x,y),(x+w,y+h),(0,255,0),2)
                        # Draw ArUco
                        if self.fsm.aruco_detector:
                            ms = self.fsm.aruco_detector.detect(display)
                            self.fsm.aruco_detector.draw_markers(display, ms)
                        # Encode as JPEG
                        _, jpeg = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 60])
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    except Exception:
                        pass
                    time.sleep(0.1)  # ~10fps to save bandwidth
            return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

        # Run in daemon thread so it doesn't block
        self._thread = threading.Thread(
            target=lambda: self._app.run(
                host=self.host, port=self.port,
                debug=False, use_reloader=False,
            ),
            daemon=True,
        )
        self._thread.start()

        # Print access URL
        import socket
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "localhost"
        print(f"[Web] Phone control ready: http://{ip}:{self.port}")
        print(f"[Web] Open this URL on your phone (same WiFi network)")

    def stop(self):
        """Stop is handled by daemon thread dying with main process."""
        pass
