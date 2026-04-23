"""Web dashboard — full debug UI + phone control + live camera.

Replaces the pygame GUI when accessed via browser. Zero lag.
Logs all events to logs/sonny.log for post-session analysis.
"""

import threading
import logging
import json
import time
import os
from datetime import datetime

PHOTO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "photos"
)
os.makedirs(PHOTO_DIR, exist_ok=True)

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

/* Camera — no crop, maintain aspect ratio, center in panel */
.cam{background:#000;border-radius:8px;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center}
.cam img{max-width:100%;max-height:100%;object-fit:contain;display:block}
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

/* Keyboard drive */
.kb-help{font-size:12px;color:#8b949e;text-align:center;line-height:1.8}
.kb-row{margin:2px 0}
kbd.kb-key{display:inline-block;min-width:24px;padding:2px 8px;background:#21262d;border:1px solid #30363d;
border-radius:4px;color:#c9d1d9;font-family:'Consolas','Ubuntu Mono',monospace;font-size:12px;font-weight:700;text-align:center}
kbd.kb-key.active{background:#1f6feb;border-color:#58a6ff;color:#fff}
kbd.kb-space{min-width:120px}
kbd.kb-space.active{background:#f85149;border-color:#f85149;color:#fff}
.kb-active{margin-top:4px;font-size:11px;color:#3fb950}

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
<img id="camFeed" src="/video_feed"
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
<button class="btn" onclick="window.open('/photos','_blank')">Gallery</button>
<button class="btn" onclick="cmd('search')">Search</button>
<button class="btn" onclick="cmd('sleep')">Sleep</button>
<button class="btn stop" onclick="cmd('stop')">STOP</button>
</div></div>

<div class="card"><div class="lbl">Phone Mic (BACKUP — Pi mic is primary)</div>
<button class="btn wake" id="micBtn" style="grid-column:span 4;padding:14px;font-size:16px;font-weight:700"
 ontouchstart="startMic(event)" ontouchend="stopMic(event)"
 onmousedown="startMic(event)" onmouseup="stopMic(event)">🎤 HOLD TO TALK</button>
<div id="micStatus" style="font-size:12px;color:#8b949e;text-align:center;margin-top:4px">Pi USB mic runs continuously — use this only if Pi mic fails</div>
</div>

<div class="card"><div class="lbl">Keyboard Drive</div>
<div class="kb-help">
<div class="kb-row"><kbd class="kb-key">W</kbd> FWD</div>
<div class="kb-row"><kbd class="kb-key">A</kbd> Strafe L &nbsp; <kbd class="kb-key">S</kbd> REV &nbsp; <kbd class="kb-key">D</kbd> Strafe R</div>
<div class="kb-row"><kbd class="kb-key">Q</kbd> Turn L &nbsp; <kbd class="kb-key">E</kbd> Turn R</div>
<div class="kb-row"><kbd class="kb-key kb-space">SPACE</kbd> EMERGENCY STOP</div>
<div class="kb-active" id="kbStatus">Keys: ready</div>
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

// Keyboard drive — WASD + QE + Space
const keys={};
const keyMap={w:[30,0,0],s:[-30,0,0],a:[0,-25,0],d:[0,25,0],q:[0,0,-25],e:[0,0,25]};
function updateDrive(){
const st=document.getElementById('kbStatus');
// Highlight active keys
document.querySelectorAll('kbd.kb-key').forEach(k=>{
const letter=k.textContent.trim().toLowerCase();
if(letter==='space')k.classList.toggle('active',!!keys[' ']);
else k.classList.toggle('active',!!keys[letter]);
});
if(keys[' ']){mv(0,0,0);cmd('stop');st.textContent='EMERGENCY STOP';st.style.color='#f85149';return}
let vx=0,vy=0,omega=0;
for(const[k,v]of Object.entries(keyMap)){if(keys[k]){vx+=v[0];vy+=v[1];omega+=v[2]}}
if(vx||vy||omega){mv(vx,vy,omega);st.textContent='Driving: vx='+vx+' vy='+vy+' \u03c9='+omega;st.style.color='#58a6ff'}
else{mv(0,0,0);st.textContent='Keys: ready';st.style.color='#3fb950'}
}
document.addEventListener('keydown',e=>{
const k=e.key.toLowerCase();
if(k in keyMap||k===' '){e.preventDefault();if(!keys[k]){keys[k]=true;updateDrive()}}
});
document.addEventListener('keyup',e=>{
const k=e.key.toLowerCase();
if(k in keyMap||k===' '){e.preventDefault();delete keys[k];updateDrive()}
});

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

// Phone mic recording
let mediaRecorder=null, audioChunks=[], micStream=null;
async function startMic(e){
e.preventDefault();
const btn=document.getElementById('micBtn');
const st=document.getElementById('micStatus');
try{
if(!micStream){micStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,sampleRate:16000}})}
audioChunks=[];
mediaRecorder=new MediaRecorder(micStream,{mimeType:'audio/webm;codecs=opus'});
mediaRecorder.ondataavailable=e=>{if(e.data.size>0)audioChunks.push(e.data)};
mediaRecorder.start();
btn.style.background='#f85149';btn.textContent='🔴 RECORDING...';
st.textContent='Listening...';st.style.color='#f85149';
}catch(err){st.textContent='Mic access denied: '+err.message;st.style.color='#f85149'}}

function stopMic(e){
e.preventDefault();
const btn=document.getElementById('micBtn');
const st=document.getElementById('micStatus');
if(!mediaRecorder||mediaRecorder.state==='inactive')return;
mediaRecorder.onstop=async()=>{
const blob=new Blob(audioChunks,{type:'audio/webm'});
if(blob.size<1000){st.textContent='Too short, try again';return}
st.textContent='Transcribing...';st.style.color='#58a6ff';
const fd=new FormData();fd.append('audio',blob,'recording.webm');
try{
const r=await fetch(API+'/audio',{method:'POST',body:fd});
const d=await r.json();
if(d.text){
st.textContent='Heard: "'+d.text+'" → '+d.intent;st.style.color='#3fb950';
document.getElementById('heard').textContent=d.text;
document.getElementById('intentD').textContent=d.intent+' ('+d.confidence+')';
addLog('voice','Phone: "'+d.text+'" → '+d.intent);
}else{st.textContent='No speech detected';st.style.color='#8b949e'}
}catch(err){st.textContent='Error: '+err.message;st.style.color='#f85149'}
};
mediaRecorder.stop();
btn.style.background='';btn.textContent='🎤 HOLD TO TALK'}

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

        @self._app.route("/audio", methods=["POST"])
        def audio():
            """Receive audio from phone mic, transcribe, and process as voice command."""
            if 'audio' not in request.files:
                return jsonify({"error": "No audio file"}), 400

            audio_file = request.files['audio']
            intent = "unknown"
            confidence = "0%"
            text = ""

            try:
                import tempfile, os
                with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                    audio_file.save(tmp.name)
                    tmp_path = tmp.name

                openai_key = os.environ.get("OPENAI_API_KEY")
                if openai_key:
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=openai_key)
                        with open(tmp_path, 'rb') as f:
                            # Same model + prompt style that worked well for
                            # the Pi-mic realtime test. Declarative prompt
                            # avoids the "command list gets echoed" hallucination.
                            response = client.audio.transcriptions.create(
                                model="gpt-4o-mini-transcribe",
                                file=f,
                                language="en",
                                prompt="The robot's name is Sonny. Markers are numbered.",
                            )
                        text = response.text.strip().lower()
                        # Filter known hallucinations (non-English slips,
                        # prompt echoes, stock "thank you" Whisper fillers).
                        HALLU = {
                            "thank you.", "thanks.", "bye.", "bye!", "you.", ".", "...",
                            "the robot's name is sonny. markers are numbered.",
                            "hello sonny, follow the track, go to marker, dance, stop, patrol",
                        }
                        if text in HALLU or any(ord(c) > 127 for c in text):
                            log_event(f"Phone mic: dropped hallucination {text!r}")
                            text = ""
                    except Exception as e:
                        log_event(f"Phone mic OpenAI error: {e}")

                if not text:
                    try:
                        import subprocess
                        wav_path = tmp_path.replace('.webm', '.wav')
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", tmp_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                            capture_output=True, timeout=10
                        )
                        if os.path.exists(wav_path) and self.fsm and self.fsm.voice_listener:
                            with open(wav_path, 'rb') as f:
                                import wave
                                with wave.open(f, 'rb') as wf:
                                    audio_data = wf.readframes(wf.getnframes())
                            text = self.fsm.voice_listener._transcribe_whisper(audio_data) or ""
                            os.unlink(wav_path)
                    except Exception as e:
                        log_event(f"Phone mic fallback error: {e}")

                os.unlink(tmp_path)

                if text:
                    log_event(f"PHONE MIC (backup): '{text}'")
                    # Pi mic is primary. If it just transcribed the same utterance
                    # within the last 3s, drop the phone mic duplicate so we don't
                    # dispatch twice.
                    if self.fsm and self.fsm.voice_listener:
                        last_pi = (self.fsm.voice_listener.last_text or "").strip().lower()
                        if last_pi and last_pi == text.strip().lower():
                            log_event(f"PHONE MIC: duplicate of Pi mic, ignoring")
                            return jsonify({"text": text, "intent": "duplicate", "confidence": "0%"})
                    if self.fsm:
                        # Wake the listener first if not awake
                        if self.fsm.voice_listener and not self.fsm.voice_listener.is_awake:
                            from alfred.voice.listener import WAKE_VARIANTS
                            woke = False
                            for wake in WAKE_VARIANTS:
                                if wake in text.lower():
                                    after = text.lower().split(wake, 1)[-1].strip()
                                    self.fsm.voice_listener._do_wake("")
                                    text = after if after else text
                                    woke = True
                                    break
                            if not woke:
                                # Auto-wake from phone mic — demo convenience
                                self.fsm.voice_listener._do_wake("")

                        # Dispatch through FSM (classifies intent internally)
                        self.fsm._on_voice_command(text)

                        # Get intent for the JSON response without re-classifying
                        if self.fsm.intent_classifier:
                            intent_name, conf = self.fsm.intent_classifier.classify(text)
                            intent = intent_name
                            confidence = f"{conf:.0%}"

            except Exception as e:
                log_event(f"Phone mic error: {e}")
                return jsonify({"error": str(e)}), 500

            return jsonify({"text": text, "intent": intent, "confidence": confidence})

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
                        # IMPORTANT: copy to avoid modifying shared frame
                        display = frame.copy()
                        h, w = display.shape[:2]

                        # Draw center crosshair (thin green lines)
                        cv2.line(display, (w//2, 0), (w//2, h), (0, 100, 0), 1)
                        cv2.line(display, (0, h//2), (w, h//2), (0, 100, 0), 1)

                        # Draw frame size for debugging
                        cv2.putText(display, f"{w}x{h}", (10, h-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)

                        # Draw faces
                        if self.fsm._last_faces:
                            for face in self.fsm._last_faces:
                                fx,fy,fw,fh = face["bbox"]
                                cv2.rectangle(display,(fx,fy),(fx+fw,fy+fh),(0,255,0),2)
                                conf = face.get("confidence", 0)
                                cv2.putText(display,f"Face {conf:.0%}",(fx,fy-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)

                        # Draw ArUco markers (use cached results — no re-detect)
                        if self.fsm.aruco_detector and self.fsm._last_markers:
                            self.fsm.aruco_detector.draw_markers(display, self.fsm._last_markers)

                        # Draw obstacles
                        if self.fsm._last_obstacles:
                            for obs in self.fsm._last_obstacles:
                                if "bbox" in obs:
                                    ox,oy,ow,oh = obs["bbox"]
                                    cv2.rectangle(display,(ox,oy),(ox+ow,oy+oh),(0,0,255),2)

                        # Encode FULL frame as JPEG — no resize
                        _, jpeg = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    except Exception:
                        pass
                    time.sleep(0.1)  # ~10fps
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

        @self._app.route("/photos")
        def photos():
            """Gallery — only rendered when the user navigates here
            (voice: 'show me picture', button, or direct URL). The main
            dashboard never embeds these, so they are loaded on demand only."""
            try:
                entries = []
                for fn in sorted(os.listdir(PHOTO_DIR), reverse=True):
                    if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    fp = os.path.join(PHOTO_DIR, fn)
                    try:
                        mtime = os.path.getmtime(fp)
                    except OSError:
                        continue
                    entries.append({
                        "name": fn,
                        "url": f"/photo/{fn}",
                        "taken": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "mtime": mtime,
                    })
                last = entries[0]["taken"] if entries else "no photos yet"
                cards = "".join(
                    f'<div class="p-card"><a href="{e["url"]}" target="_blank">'
                    f'<img src="{e["url"]}" loading="lazy"></a>'
                    f'<div class="p-meta">{e["name"]}<br><span>{e["taken"]}</span></div></div>'
                    for e in entries
                ) or '<p style="color:#8b949e">No photos yet. Say "take a photo" to capture one.</p>'
                return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Sonny Gallery</title>
<style>
body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;margin:0;padding:12px}}
h1{{color:#58a6ff;margin:0 0 8px 0}}
.bar{{color:#8b949e;font-size:13px;margin-bottom:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
.p-card{{background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}}
.p-card img{{width:100%;display:block;aspect-ratio:4/3;object-fit:cover}}
.p-meta{{padding:6px 8px;font-size:11px;color:#c9d1d9}}
.p-meta span{{color:#8b949e}}
a{{color:#58a6ff;text-decoration:none}}
</style></head><body>
<h1>Sonny — Photo Gallery</h1>
<div class="bar">Last taken: <b>{last}</b> &nbsp; · &nbsp; <a href="/">← Dashboard</a></div>
<div class="grid">{cards}</div>
</body></html>"""
            except Exception as e:
                return f"Gallery error: {e}", 500

        @self._app.route("/photo/<path:name>")
        def photo_file(name):
            """Serve a single photo file."""
            from flask import send_from_directory, abort
            safe = os.path.basename(name)
            if not safe or safe != name:
                abort(404)
            full = os.path.join(PHOTO_DIR, safe)
            if not os.path.isfile(full):
                abort(404)
            return send_from_directory(PHOTO_DIR, safe)

        @self._app.route("/photos.json")
        def photos_json():
            """JSON list of photos — used by voice/gallery integrations."""
            out = []
            try:
                for fn in sorted(os.listdir(PHOTO_DIR), reverse=True):
                    if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    fp = os.path.join(PHOTO_DIR, fn)
                    try:
                        mtime = os.path.getmtime(fp)
                    except OSError:
                        continue
                    out.append({
                        "name": fn,
                        "url": f"/photo/{fn}",
                        "taken": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
            except Exception:
                pass
            return jsonify({"photos": out, "count": len(out)})

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
