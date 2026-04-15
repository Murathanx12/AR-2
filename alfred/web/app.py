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
<title>Sonny Control</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px;
}
h1 { color: #58a6ff; font-size: 28px; margin: 12px 0 4px; }
.status { font-size: 14px; color: #8b949e; margin-bottom: 20px; }
.status.connected { color: #3fb950; }
.status.error { color: #f85149; }

.mic-btn {
    width: 120px; height: 120px;
    border-radius: 50%;
    border: 3px solid #30363d;
    background: #161b22;
    color: #58a6ff;
    font-size: 48px;
    cursor: pointer;
    transition: all 0.2s;
    margin: 16px 0;
}
.mic-btn:active, .mic-btn.listening {
    background: #1f6feb;
    color: white;
    border-color: #58a6ff;
    transform: scale(1.1);
}
.mic-btn.listening {
    animation: pulse 1s infinite;
}
@keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(88,166,255,0.4); }
    50% { box-shadow: 0 0 0 20px rgba(88,166,255,0); }
}

.result {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 16px;
    width: 100%;
    max-width: 400px;
    margin: 8px 0;
    min-height: 60px;
}
.result .label { font-size: 12px; color: #8b949e; margin-bottom: 4px; }
.result .text { font-size: 18px; color: #e6edf3; }
.result .intent { font-size: 14px; color: #3fb950; margin-top: 4px; }
.result .response { font-size: 14px; color: #58a6ff; margin-top: 4px; }

.quick-btns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
    max-width: 400px;
    margin: 12px 0;
}
.quick-btn {
    padding: 14px 8px;
    border-radius: 10px;
    border: 1px solid #30363d;
    background: #161b22;
    color: #c9d1d9;
    font-size: 15px;
    cursor: pointer;
    text-align: center;
}
.quick-btn:active { background: #1f6feb; color: white; }
.quick-btn.stop { border-color: #f85149; color: #f85149; grid-column: span 2; font-size: 20px; font-weight: bold; }
.quick-btn.stop:active { background: #f85149; color: white; }

.log { font-size: 12px; color: #484f58; margin-top: 16px; max-width: 400px; width: 100%; }
.log div { padding: 2px 0; border-bottom: 1px solid #21262d; }
</style>
</head>
<body>

<h1>SONNY</h1>
<div class="status" id="status">Tap mic or use quick buttons</div>

<button class="mic-btn" id="micBtn" onclick="toggleMic()">&#127908;</button>

<div class="result">
    <div class="label">You said:</div>
    <div class="text" id="heardText">-</div>
    <div class="intent" id="intentText"></div>
    <div class="response" id="responseText"></div>
</div>

<div class="quick-btns">
    <button class="quick-btn" onclick="sendCmd('hello sonny')">Wake Up</button>
    <button class="quick-btn" onclick="sendCmd('follow track')">Follow Track</button>
    <button class="quick-btn" onclick="sendCmd('go to qr code')">Go to QR Code</button>
    <button class="quick-btn" onclick="sendCmd('dance')">Dance</button>
    <button class="quick-btn" onclick="sendCmd('patrol')">Patrol</button>
    <button class="quick-btn" onclick="sendCmd('photo')">Photo</button>
    <button class="quick-btn" onclick="sendCmd('come here')">Come Here</button>
    <button class="quick-btn" onclick="sendCmd('sleep')">Sleep</button>
    <button class="quick-btn stop" onclick="sendCmd('stop')">STOP</button>
</div>

<div class="log" id="log"></div>

<script>
const API = window.location.origin;
let recognition = null;
let listening = false;

// Setup Web Speech API
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = function(event) {
        const text = event.results[0][0].transcript;
        document.getElementById('heardText').textContent = text;
        sendCmd(text);
        stopMic();
    };
    recognition.onerror = function(event) {
        log('Mic error: ' + event.error);
        stopMic();
    };
    recognition.onend = function() { stopMic(); };
} else {
    document.getElementById('status').textContent = 'Speech recognition not supported in this browser';
    document.getElementById('status').className = 'status error';
}

function toggleMic() {
    if (listening) { stopMic(); }
    else { startMic(); }
}

function startMic() {
    if (!recognition) return;
    listening = true;
    document.getElementById('micBtn').classList.add('listening');
    document.getElementById('status').textContent = 'Listening...';
    document.getElementById('status').className = 'status connected';
    recognition.start();
}

function stopMic() {
    listening = false;
    document.getElementById('micBtn').classList.remove('listening');
    document.getElementById('status').textContent = 'Tap mic or use quick buttons';
    document.getElementById('status').className = 'status';
    try { recognition.stop(); } catch(e) {}
}

function sendCmd(text) {
    document.getElementById('heardText').textContent = text;
    document.getElementById('intentText').textContent = 'Sending...';
    document.getElementById('responseText').textContent = '';
    log('Sent: ' + text);

    fetch(API + '/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})
    })
    .then(r => r.json())
    .then(data => {
        document.getElementById('intentText').textContent = 'Intent: ' + data.intent + ' (' + data.confidence + ')';
        document.getElementById('responseText').textContent = data.response || '';
        document.getElementById('status').textContent = 'Command received';
        document.getElementById('status').className = 'status connected';
        log('Response: ' + data.intent);
    })
    .catch(err => {
        document.getElementById('intentText').textContent = 'Error: ' + err.message;
        document.getElementById('status').textContent = 'Connection failed';
        document.getElementById('status').className = 'status error';
        log('Error: ' + err.message);
    });
}

function log(msg) {
    const logEl = document.getElementById('log');
    const time = new Date().toLocaleTimeString();
    logEl.innerHTML = '<div>' + time + ' ' + msg + '</div>' + logEl.innerHTML;
    if (logEl.children.length > 10) logEl.removeChild(logEl.lastChild);
}
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
            """Return current robot state for polling."""
            state = "IDLE"
            if self.fsm:
                from alfred.fsm.states import STATE_NAMES
                state = STATE_NAMES.get(self.fsm.state, "?")
            return jsonify({"state": state})

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
