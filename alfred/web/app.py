"""Web dashboard — full debug UI + phone control + live camera.

Replaces the pygame GUI when accessed via browser. Zero lag.
Logs all events to logs/sonny.log for post-session analysis.
"""

import threading
import logging
import json
import time
import os

logger = logging.getLogger(__name__)

try:
    from flask import Flask, request, jsonify, render_template_string, Response
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

# Setup file logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "sonny.log")

_file_logger = logging.getLogger("sonny_file")
_file_logger.setLevel(logging.DEBUG)
try:
    _fh = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
    _file_logger.addHandler(_fh)
except Exception:
    pass


def log_event(msg):
    """Log to file and return for web display."""
    _file_logger.info(msg)
    print(f"[LOG] {msg}")


_HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>SONNY Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;overflow:hidden}

.grid{display:grid;height:100vh;grid-template-columns:1fr 380px;grid-template-rows:52px 1fr 44px;gap:4px;padding:4px}

/* Header */
.hdr{grid-column:span 2;background:#161b22;border-radius:8px;display:flex;align-items:center;padding:0 12px;gap:12px}
.hdr h1{color:#58a6ff;font-size:22px;font-weight:800}
.pill{padding:3px 14px;border-radius:12px;font-size:14px;font-weight:700}
.hdr .voice-heard{flex:1;text-align:right;font-size:13px;color:#8b949e;overflow:hidden;white-space:nowrap}
.hdr .voice-heard b{color:#58a6ff}
.hdr .voice-intent{color:#3fb950;font-size:13px;margin-left:8px}

/* Camera */
.cam{background:#161b22;border-radius:8px;position:relative;overflow:hidden}
.cam img{width:100%;height:100%;object-fit:contain;display:block}
.cam .overlay{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.7);padding:6px 10px;font-size:12px}
.cam .overlay span{margin-right:14px}
.cam .no-feed{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#484f58;font-size:16px}

/* Sidebar */
.side{background:#161b22;border-radius:8px;display:flex;flex-direction:column;gap:4px;padding:6px;overflow-y:auto}
.card{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 8px}
.card .lbl{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px}

/* IR */
.ir-row{display:flex;gap:3px;justify-content:center}
.ir-dot{width:44px;height:26px;border-radius:4px;display:flex;align-items:center;justify-content:center;
font-size:12px;font-weight:700;transition:all 0.2s}
.ir-on{background:#238636;color:#fff;box-shadow:0 0 8px #23863666}
.ir-off{background:#21262d;color:#484f58}

/* Values */
.val{font-size:16px;font-weight:600;font-family:'Consolas','Ubuntu Mono',monospace}
.val.danger{color:#f85149}
.val.ok{color:#3fb950}
.val.blue{color:#79c0ff}

/* Motor */
.motor-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;text-align:center}
.motor-grid .mv{font-size:13px;color:#8b949e}
.motor-grid .mv b{font-size:16px;display:block}

/* Buttons */
.btns{display:grid;grid-template-columns:repeat(4,1fr);gap:3px}
.btn{padding:8px 2px;border-radius:6px;border:1px solid #30363d;background:#161b22;color:#c9d1d9;
font-size:12px;cursor:pointer;text-align:center;transition:all 0.1s}
.btn:active{background:#1f6feb;color:#fff;transform:scale(0.96)}
.btn.stop{background:#f8514922;border-color:#f85149;color:#f85149;font-size:15px;font-weight:800;grid-column:span 2}
.btn.stop:active{background:#f85149;color:#fff}
.btn.wake{background:#1f6feb22;border-color:#1f6feb;color:#58a6ff}

/* Log */
.log-box{flex:1;min-height:0;overflow-y:auto;font-family:'Consolas','Ubuntu Mono',monospace;font-size:11px;padding:4px}
.log-box div{padding:1px 0;border-bottom:1px solid #21262d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.log-box .cmd{color:#58a6ff}
.log-box .intent{color:#3fb950}
.log-box .state{color:#d29922}
.log-box .voice{color:#bc8cff}
.log-box .err{color:#f85149}

/* Footer */
.foot{grid-column:span 2;background:#161b22;border-radius:8px;display:flex;align-items:center;padding:0 12px;
font-size:11px;color:#484f58;gap:20px}
.foot .live{width:8px;height:8px;border-radius:50%;background:#3fb950;animation:blink 1s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
</style>
</head>
<body>
<div class="grid">

<!-- HEADER -->
<div class="hdr">
<h1>SONNY</h1>
<span class="pill" id="stPill" style="background:#30363d;color:#8b949e">IDLE</span>
<span class="voice-heard">Heard: <b id="heard">-</b></span>
<span class="voice-intent" id="intentD"></span>
</div>

<!-- CAMERA — preserve aspect ratio, no crop -->
<div class="cam">
<img id="camFeed" src="/video_feed" style="width:100%;height:100%;object-fit:contain;background:#000"
 onerror="this.style.display='none';document.getElementById('noFeed').style.display='block'">
<span class="no-feed" id="noFeed" style="display:none">No Camera Feed</span>
<div class="overlay">
<span id="camMarkers" style="color:#3fb950"></span>
<span id="camFaces" style="color:#58a6ff"></span>
</div>
</div>

<!-- SIDEBAR -->
<div class="side">

<div class="card"><div class="lbl">State</div>
<div class="val blue" id="stName" style="font-size:20px">IDLE</div>
<div style="font-size:11px;color:#8b949e" id="stDesc">Waiting for wake word</div>
</div>

<div class="card"><div class="lbl">IR Sensors</div>
<div class="ir-row" id="irRow">
<div class="ir-dot ir-off">W</div><div class="ir-dot ir-off">NW</div>
<div class="ir-dot ir-off">N</div><div class="ir-dot ir-off">NE</div>
<div class="ir-dot ir-off">E</div>
</div></div>

<div class="card"><div class="lbl">Ultrasonic</div>
<div class="val ok" id="dist">---</div></div>

<div class="card"><div class="lbl">Movement</div>
<div class="motor-grid">
<div class="mv">VX<b id="mvx" class="val blue">0</b></div>
<div class="mv">VY<b id="mvy" class="val blue">0</b></div>
<div class="mv">OMEGA<b id="mvo" class="val blue">0</b></div>
</div></div>

<div class="card"><div class="lbl">Voice (Whisper)</div>
<div id="voiceText" style="font-size:13px;color:#bc8cff;min-height:18px">-</div></div>

<div class="card"><div class="lbl">Voice Commands</div>
<div class="btns">
<button class="btn wake" onclick="cmd('hello sonny')">Wake Up</button>
<button class="btn" onclick="cmd('follow track')">Follow Track</button>
<button class="btn" onclick="cmd('follow the marker')">Any Marker</button>
<button class="btn" onclick="cmd('go to marker '+document.getElementById('mkrId').value)">Go to Marker <input id="mkrId" type="number" value="8" min="0" max="49" style="width:36px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;text-align:center;font-size:14px;font-weight:bold" onclick="event.stopPropagation()"></button>
<button class="btn" onclick="cmd('come here')">Follow Human</button>
<button class="btn" onclick="cmd('dance')">Dance</button>
<button class="btn" onclick="cmd('patrol')">Patrol</button>
<button class="btn" onclick="cmd('photo')">Photo</button>
<button class="btn" onclick="cmd('search')">Search</button>
<button class="btn" onclick="cmd('sleep')">Sleep</button>
<button class="btn stop" onclick="cmd('stop')">STOP</button>
</div></div>

<div class="card"><div class="lbl">Manual Drive</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:2px;max-width:200px;margin:0 auto">
<div></div>
<button class="btn" onmousedown="mv(30,0,0)" onmouseup="mv(0,0,0)" ontouchstart="mv(30,0,0)" ontouchend="mv(0,0,0)">FWD</button>
<div></div>
<button class="btn" onmousedown="mv(0,0,-25)" onmouseup="mv(0,0,0)" ontouchstart="mv(0,0,-25)" ontouchend="mv(0,0,0)">Turn L</button>
<button class="btn stop" onmousedown="mv(0,0,0)" style="font-size:11px;grid-column:auto">STOP</button>
<button class="btn" onmousedown="mv(0,0,25)" onmouseup="mv(0,0,0)" ontouchstart="mv(0,0,25)" ontouchend="mv(0,0,0)">Turn R</button>
<button class="btn" onmousedown="mv(0,-25,0)" onmouseup="mv(0,0,0)" ontouchstart="mv(0,-25,0)" ontouchend="mv(0,0,0)">Strafe L</button>
<button class="btn" onmousedown="mv(-30,0,0)" onmouseup="mv(0,0,0)" ontouchstart="mv(-30,0,0)" ontouchend="mv(0,0,0)">REV</button>
<button class="btn" onmousedown="mv(0,25,0)" onmouseup="mv(0,0,0)" ontouchstart="mv(0,25,0)" ontouchend="mv(0,0,0)">Strafe R</button>
</div></div>

<div class="card" style="flex:1;min-height:0;display:flex;flex-direction:column">
<div class="lbl">Event Log</div>
<div class="log-box" id="log"></div>
</div>

</div>

<!-- FOOTER -->
<div class="foot">
<div class="live"></div>
<span>Connected to Pi</span>
<span id="fps">-</span>
<span>UART: <b id="uartSt" style="color:#3fb950">OK</b></span>
<span>Engine: <b id="engine" style="color:#bc8cff">-</b></span>
<span style="flex:1"></span>
<span>http://192.168.50.9:8080</span>
</div>

</div>

<script>
const API=window.location.origin;
const stColors={IDLE:'#30363d',LISTEN:'#1f6feb',FOLLOW:'#238636',ENDPOINT:'#d29922',PARKING:'#1f6feb',
ARUCO_SRCH:'#d29922',ARUCO_APPR:'#0d8a72',BLOCKED:'#f85149',REROUTE:'#d29922',PATROL:'#238636',
PERSON:'#8b5cf6',DANCE:'#db61a2',PHOTO:'#d29922',LOST_REV:'#f85149',LOST_PIVOT:'#f85149',
STOPPING:'#484f58',SLEEP:'#21262d'};
const stDescs={IDLE:'Waiting for wake word',LISTEN:'Listening for command...',FOLLOW:'Following the track',
ENDPOINT:'Reaching destination',PARKING:'Parking at delivery',ARUCO_SRCH:'Scanning for marker',
ARUCO_APPR:'Approaching marker',BLOCKED:'Obstacle detected!',REROUTE:'Finding another way',
PATROL:'Patrolling area',PERSON:'Approaching person',DANCE:'Dancing!',PHOTO:'Taking photo',
LOST_REV:'Recovering track',LOST_PIVOT:'Searching for line',STOPPING:'Stopping...',SLEEP:'Sleeping'};
let lastVoice='',logCount=0;

function cmd(text){
addLog('cmd','> '+text);
fetch(API+'/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})})
.then(r=>r.json()).then(d=>{
document.getElementById('heard').textContent=text;
document.getElementById('intentD').textContent=d.intent+' ('+d.confidence+')';
addLog('intent','= '+d.intent+' ('+d.confidence+')');
}).catch(e=>addLog('err','! '+e.message))}

function mv(vx,vy,omega){
fetch(API+'/move',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({vx,vy,omega})}).catch(()=>{})}

function addLog(cls,msg){
const l=document.getElementById('log');logCount++;
const t=new Date().toLocaleTimeString().slice(0,8);
l.innerHTML='<div class="'+cls+'">'+t+' '+msg+'</div>'+l.innerHTML;
if(l.children.length>50)l.removeChild(l.lastChild)}

// Poll status every 400ms
setInterval(()=>{
fetch(API+'/status').then(r=>r.json()).then(d=>{
// State
const st=d.state||'IDLE';
document.getElementById('stPill').textContent=st;
document.getElementById('stPill').style.background=stColors[st]||'#30363d';
document.getElementById('stPill').style.color='#fff';
document.getElementById('stName').textContent=st;
document.getElementById('stDesc').textContent=stDescs[st]||'';

// IR
const names=['W','NW','N','NE','E'];
document.getElementById('irRow').innerHTML=
(d.ir||[0,0,0,0,0]).map((v,i)=>'<div class="ir-dot '+(v?'ir-on':'ir-off')+'">'+names[i]+'</div>').join('');

// Ultrasonic
const dist=d.dist||0;
const de=document.getElementById('dist');
de.textContent=dist>0?dist+'cm':'No sensor';
de.className='val '+(dist>0&&dist<20?'danger':'ok');

// Motor
document.getElementById('mvx').textContent=(d.vx||0)>0?'+'+d.vx:d.vx||'0';
document.getElementById('mvy').textContent=(d.vy||0)>0?'+'+d.vy:d.vy||'0';
document.getElementById('mvo').textContent=(d.omega||0)>0?'+'+d.omega:d.omega||'0';

// Voice
const v=d.voice||'';
if(v&&v!==lastVoice){lastVoice=v;
document.getElementById('voiceText').textContent='"'+v+'"';
document.getElementById('heard').textContent=v;
addLog('voice','Whisper: "'+v+'"')}

// Detection
document.getElementById('camFaces').textContent=d.faces?'Faces: '+d.faces:'';

// Engine
document.getElementById('engine').textContent=d.engine||'whisper';
document.getElementById('uartSt').textContent=d.uart?'Connected':'Disconnected';
document.getElementById('uartSt').style.color=d.uart?'#3fb950':'#f85149';

// State changes
if(d.state_changed)addLog('state','State: '+d.state_changed);
}).catch(()=>{})},400);
</script>
</body>
</html>
"""


class WebController:
    """Web dashboard with live camera, sensors, voice, commands, and logging."""

    def __init__(self, fsm=None, host="0.0.0.0", port=8080):
        self.fsm = fsm
        self.host = host
        self.port = port
        self._thread = None
        self._app = None
        self._last_state = None

    def start(self):
        if not _HAS_FLASK:
            print("[Web] Flask not installed. Run: pip install flask")
            return

        self._app = Flask(__name__)
        self._app.logger.setLevel(logging.WARNING)

        @self._app.route("/")
        def index():
            return render_template_string(_HTML_PAGE)

        @self._app.route("/command", methods=["POST"])
        def command():
            data = request.get_json(silent=True) or {}
            text = data.get("text", "").strip()
            if not text:
                return jsonify({"error": "No text"}), 400

            intent = "unknown"
            confidence = "0%"

            if self.fsm and self.fsm.intent_classifier:
                intent_name, conf = self.fsm.intent_classifier.classify(text)
                intent = intent_name
                confidence = f"{conf:.0%}"
                log_event(f"CMD: '{text}' -> {intent} ({confidence})")

                self.fsm._on_voice_command(text)

                if self.fsm.voice_listener and not self.fsm.voice_listener.is_awake:
                    from alfred.voice.listener import WAKE_VARIANTS
                    for wake in WAKE_VARIANTS:
                        if wake in text.lower():
                            self.fsm.voice_listener._do_wake(
                                text.lower().split(wake, 1)[-1].strip()
                            )
                            break

            return jsonify({"intent": intent, "confidence": confidence, "text": text})

        @self._app.route("/move", methods=["POST"])
        def move():
            """Direct motor control from web UI."""
            data = request.get_json(silent=True) or {}
            vx = int(data.get("vx", 0))
            vy = int(data.get("vy", 0))
            omega = int(data.get("omega", 0))
            if self.fsm and self.fsm.uart:
                from alfred.comms.protocol import cmd_vector, cmd_stop
                if vx == 0 and vy == 0 and omega == 0:
                    self.fsm.uart.send(cmd_stop())
                else:
                    self.fsm.uart.send(cmd_vector(vx, vy, omega))
                if self.fsm.line_follower:
                    self.fsm.line_follower.debug_vx = vx
                    self.fsm.line_follower.debug_vy = vy
                    self.fsm.line_follower.debug_omega = omega
            return jsonify({"ok": True})

        @self._app.route("/status")
        def status():
            from alfred.fsm.states import STATE_NAMES
            result = {
                "state": "IDLE", "ir": [0,0,0,0,0], "dist": -1,
                "vx": 0, "vy": 0, "omega": 0, "faces": 0,
                "voice": "", "engine": "none", "uart": False,
                "state_changed": None,
            }

            if self.fsm:
                st = STATE_NAMES.get(self.fsm.state, "?")
                result["state"] = st

                if self.fsm.uart:
                    result["uart"] = self.fsm.uart.is_open
                    if self.fsm.uart.is_open:
                        result["ir"] = self.fsm.uart.get_ir_bits()
                        result["dist"] = round(self.fsm.uart.get_distance(), 1)

                lf = self.fsm.line_follower
                if lf:
                    result["vx"] = lf.debug_vx
                    result["vy"] = lf.debug_vy
                    result["omega"] = lf.debug_omega

                result["faces"] = len(self.fsm._last_faces) if self.fsm._last_faces else 0

                if self.fsm.voice_listener:
                    result["voice"] = self.fsm.voice_listener.last_text
                    result["engine"] = self.fsm.voice_listener.engine

                # Detect state changes for log
                if st != self._last_state:
                    if self._last_state:
                        result["state_changed"] = f"{self._last_state} -> {st}"
                        log_event(f"STATE: {self._last_state} -> {st}")
                    self._last_state = st

            return jsonify(result)

        @self._app.route("/video_feed")
        def video_feed():
            def generate():
                while True:
                    if not self.fsm or not self.fsm.camera:
                        time.sleep(0.2)
                        continue
                    frame = self.fsm._last_frame
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    try:
                        import cv2
                        display = frame.copy()
                        if self.fsm._last_faces:
                            for face in self.fsm._last_faces:
                                x,y,w,h = face["bbox"]
                                cv2.rectangle(display,(x,y),(x+w,y+h),(0,255,0),2)
                                conf = face.get("confidence", 0)
                                cv2.putText(display,f"Face {conf:.0%}",(x,y-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)
                        if self.fsm.aruco_detector:
                            ms = self.fsm.aruco_detector.detect(display)
                            self.fsm.aruco_detector.draw_markers(display, ms)
                        if self.fsm._last_obstacles:
                            for obs in self.fsm._last_obstacles:
                                if "bbox" in obs:
                                    x,y,w,h = obs["bbox"]
                                    cv2.rectangle(display,(x,y),(x+w,y+h),(0,0,255),2)
                        # Send full frame — browser handles scaling via object-fit:contain
                        _, jpeg = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    except Exception:
                        pass
                    time.sleep(0.1)
            return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

        @self._app.route("/logs")
        def logs():
            """Return recent log entries."""
            try:
                with open(LOG_PATH, 'r') as f:
                    lines = f.readlines()[-100:]
                return jsonify({"logs": [l.strip() for l in lines]})
            except Exception:
                return jsonify({"logs": []})

        self._thread = threading.Thread(
            target=lambda: self._app.run(
                host=self.host, port=self.port,
                debug=False, use_reloader=False,
                threaded=True,
            ),
            daemon=True,
        )
        self._thread.start()

        import socket
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "localhost"
        print(f"[Web] Dashboard ready: http://{ip}:{self.port}")
        log_event(f"Web dashboard started on port {self.port}")

    def stop(self):
        pass
