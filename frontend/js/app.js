/**
 * Tiago Web Interface — main application logic.
 * Handles WebSocket, safety display, block execution, launch panel.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const WS_URL      = `ws://${location.host}/ws`;
const EXECUTE_URL = `${location.origin}/execute`;
const ABORT_URL   = `${location.origin}/abort`;

// Camera feed served directly from robot via web_video_server
const CAMERA_TOPIC  = "/xtion/rgb/image_raw";
const CAMERA_URL    = `http://bandit:8080/stream?topic=${CAMERA_TOPIC}&type=mjpeg`;

// ---------------------------------------------------------------------------
// Blockly workspace
// ---------------------------------------------------------------------------
const toolbox = {
  kind: "categoryToolbox",
  contents: [
    {
      kind: "category",
      name: "Motion",
      colour: "160",
      contents: [
        { kind: "block", type: "move_forward" },
        { kind: "block", type: "move_backward" },
        { kind: "block", type: "turn_left" },
        { kind: "block", type: "turn_right" },
        { kind: "block", type: "stop" },
        { kind: "block", type: "wait" },
      ]
    },
    {
      kind: "category",
      name: "Control",
      colour: "210",
      contents: [
        { kind: "block", type: "if_else" },
      ]
    },
    {
      kind: "category",
      name: "Sensors",
      colour: "20",
      contents: [
        { kind: "block", type: "lidar_compare" },
      ]
    }
  ]
};

const workspace = Blockly.inject("blockly-div", {
  toolbox,
  scrollbars: true,
  trashcan: true,
  zoom: { controls: true, wheel: true, startScale: 1.0 },
  theme: Blockly.Themes.Dark,
  renderer: 'zelos',
});

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const safetyBar     = document.getElementById("safety-bar");
const safetyLabel   = document.getElementById("safety-label");
const safetyDist    = document.getElementById("safety-dist");
const eStopBtn      = document.getElementById("emergency-stop");
const executeBtn    = document.getElementById("execute-btn");
const clearBtn      = document.getElementById("clear-btn");
const execLog       = document.getElementById("exec-log");
const launchLog     = document.getElementById("launch-log");
const cameraImg     = document.getElementById("camera-img");
const noCamera      = document.getElementById("no-camera");
const rosBridgeBtn  = document.getElementById("btn-rosbridge");
const videoSrvBtn   = document.getElementById("btn-video-server");
const rosStatus     = document.getElementById("ros-status");

// ---------------------------------------------------------------------------
// Safety state → UI
// ---------------------------------------------------------------------------
const SAFETY_STYLES = {
  CLEAR:        { bar: "bg-green-700",  text: "● CLEAR",       dist: true  },
  WARNING:      { bar: "bg-yellow-500", text: "⚠ WARNING",     dist: true  },
  DANGER:       { bar: "bg-red-700",    text: "✖ DANGER — STOPPED", dist: true },
  DISCONNECTED: { bar: "bg-gray-600",   text: "◌ NO LIDAR",    dist: false },
};

let currentSafetyState = "DISCONNECTED";

function updateSafetyUI(state, min_dist) {
  currentSafetyState = state;
  const style = SAFETY_STYLES[state] || SAFETY_STYLES.DISCONNECTED;

  safetyBar.className = `flex items-center justify-between px-4 py-2 ${style.bar} transition-colors duration-300`;
  safetyLabel.textContent = style.text;
  safetyDist.textContent  = (style.dist && min_dist != null)
    ? `${min_dist.toFixed(2)} m`
    : "";

  // Play audio cue on WARNING
  if (state === "WARNING" && currentSafetyState !== "WARNING") {
    playBeep(440, 0.15);
  }
  if (state === "DANGER") {
    playBeep(880, 0.3);
  }
}

// ---------------------------------------------------------------------------
// Execution log
// ---------------------------------------------------------------------------
function logExec(msg, cls = "text-gray-300") {
  const line = document.createElement("div");
  line.className = cls;
  line.textContent = `[${timestamp()}] ${msg}`;
  execLog.appendChild(line);
  execLog.scrollTop = execLog.scrollHeight;
}

function handleExecutionMsg(data) {
  const { status, step, total, block, reason, message } = data;
  switch (status) {
    case "running":
      logExec(`▶ Step ${step}/${total}: ${block}`, "text-blue-300");
      break;
    case "step_done":
      logExec(`✔ Step ${step}/${total} done`, "text-green-400");
      break;
    case "completed":
      logExec("✔ Sequence completed.", "text-green-300 font-bold");
      setExecuting(false);
      break;
    case "aborted":
      logExec(`✖ Aborted at step ${step}/${total} — ${reason || ""}`, "text-red-400");
      setExecuting(false);
      break;
    case "error":
      logExec(`✖ Error: ${message}`, "text-red-500");
      setExecuting(false);
      break;
  }
}

// ---------------------------------------------------------------------------
// Launch log
// ---------------------------------------------------------------------------
function logLaunch(service, line, level = "info") {
  const el = document.createElement("div");
  el.className = level === "error" ? "text-red-400"
               : level === "warn"  ? "text-yellow-400"
               : "text-gray-400";
  el.textContent = `[${service}] ${line}`;
  launchLog.appendChild(el);
  launchLog.scrollTop = launchLog.scrollHeight;
}

// ---------------------------------------------------------------------------
// Service status badges
// ---------------------------------------------------------------------------
function updateServiceStatus(services) {
  const rb = services["rosbridge"] || false;
  const vs = services["web_video_server"] || false;

  rosBridgeBtn.textContent = rb ? "● ROSBridge" : "○ ROSBridge";
  rosBridgeBtn.className   = rb
    ? "px-3 py-1 rounded text-sm font-mono bg-green-700 hover:bg-green-800"
    : "px-3 py-1 rounded text-sm font-mono bg-gray-600 hover:bg-gray-500";

  videoSrvBtn.textContent  = vs ? "● Video Server" : "○ Video Server";
  videoSrvBtn.className    = vs
    ? "px-3 py-1 rounded text-sm font-mono bg-green-700 hover:bg-green-800"
    : "px-3 py-1 rounded text-sm font-mono bg-gray-600 hover:bg-gray-500";

  // Update camera src when video server comes up
  if (vs) {
    cameraImg.src = CAMERA_URL;
    cameraImg.classList.remove("hidden");
    noCamera.classList.add("hidden");
  }
}

// ---------------------------------------------------------------------------
// Execute / abort
// ---------------------------------------------------------------------------
let _executing = false;

function setExecuting(val) {
  _executing = val;
  executeBtn.disabled = val;
  executeBtn.textContent = val ? "⏳ Running…" : "▶ Execute";
}

executeBtn.addEventListener("click", async () => {
  const commands = workspaceToCommands(workspace);
  if (!commands.length) {
    logExec("No blocks in workspace.", "text-yellow-400");
    return;
  }
  if (currentSafetyState === "DANGER") {
    logExec("Cannot execute — safety DANGER state active.", "text-red-400");
    return;
  }

  logExec(`Sending ${commands.length} block(s)…`, "text-gray-400");
  setExecuting(true);

  try {
    const res = await fetch(EXECUTE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blocks: commands }),
    });
    if (!res.ok) {
      const err = await res.json();
      logExec(`Server error: ${err.detail}`, "text-red-400");
      setExecuting(false);
    }
  } catch (e) {
    logExec(`Network error: ${e}`, "text-red-400");
    setExecuting(false);
  }
});

async function sendAbort() {
  try {
    await fetch(ABORT_URL, { method: "POST" });
  } catch (e) {
    console.error("Abort request failed:", e);
  }
}

eStopBtn.addEventListener("click", () => {
  sendAbort();
  logExec("⬛ EMERGENCY STOP pressed.", "text-red-300 font-bold");
  setExecuting(false);
});

clearBtn.addEventListener("click", () => {
  workspace.clear();
  execLog.innerHTML = "";
});

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
let ws;
let wsReconnectDelay = 1000;

function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    rosStatus.textContent = "● Connected";
    rosStatus.className   = "text-green-400 font-mono text-sm";
    wsReconnectDelay = 1000;
  };

  ws.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }

    switch (data.type) {
      case "safety":
        updateSafetyUI(data.state, data.min_dist);
        if (data.ros_ready !== undefined) {
          rosStatus.textContent = data.ros_ready ? "● ROS Ready" : "◌ ROS Connecting…";
          rosStatus.className   = data.ros_ready
            ? "text-green-400 font-mono text-sm"
            : "text-yellow-400 font-mono text-sm";
          rosBridgeBtn.disabled = data.ros_ready;
          rosBridgeBtn.title    = data.ros_ready ? "ROSBridge already connected" : "";
        }
        break;
      case "execution":
        handleExecutionMsg(data);
        break;
      case "launch_log":
        logLaunch(data.service, data.line, data.level);
        break;
      case "service_status":
        updateServiceStatus(data.services);
        break;
    }
  };

  ws.onclose = () => {
    rosStatus.textContent = "○ Disconnected";
    rosStatus.className   = "text-red-400 font-mono text-sm";
    updateSafetyUI("DISCONNECTED", null);
    setTimeout(connectWS, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 2, 10000);
  };

  ws.onerror = () => ws.close();
}

// Launch buttons — toggle: if running send stop_service, else launch
rosBridgeBtn.addEventListener("click", () => {
  const running = rosBridgeBtn.textContent.startsWith("●");
  ws.send(JSON.stringify({ type: running ? "stop_service" : "launch", service: "rosbridge" }));
});

videoSrvBtn.addEventListener("click", () => {
  const running = videoSrvBtn.textContent.startsWith("●");
  ws.send(JSON.stringify({ type: running ? "stop_service" : "launch", service: "web_video_server" }));
});

// Camera image error → show placeholder
cameraImg.addEventListener("error", () => {
  cameraImg.classList.add("hidden");
  noCamera.classList.remove("hidden");
});

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function timestamp() {
  const d = new Date();
  return d.toTimeString().slice(0, 8);
}

let _audioCtx;
function playBeep(freq, duration) {
  try {
    if (!_audioCtx) _audioCtx = new AudioContext();
    const osc  = _audioCtx.createOscillator();
    const gain = _audioCtx.createGain();
    osc.connect(gain);
    gain.connect(_audioCtx.destination);
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.1, _audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + duration);
    osc.start();
    osc.stop(_audioCtx.currentTime + duration);
  } catch { /* audio not critical */ }
}

// ---------------------------------------------------------------------------
// Fix: preserve scroll position when blocks are added from the flyout.
// Blockly can reset the workspace viewport after flyout closes, making
// previously placed blocks scroll off-screen ("vanish").
// ---------------------------------------------------------------------------
(function () {
  let scrollX = 0;
  let scrollY = 0;

  // Capture scroll before the flyout interaction
  workspace.addChangeListener(function (event) {
    if (event.type === Blockly.Events.BLOCK_CREATE) {
      // Restore the scroll position the user had before clicking the flyout
      workspace.scroll(scrollX, scrollY);
    } else if (
      event.type !== Blockly.Events.BLOCK_DRAG &&
      event.type !== Blockly.Events.SELECTED
    ) {
      // Keep tracking current scroll so we can restore it
      scrollX = workspace.scrollX;
      scrollY = workspace.scrollY;
    }
  });
})();

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
window.addEventListener("resize", () => Blockly.svgResize(workspace));
connectWS();
logExec("Interface ready. Build your block sequence and click Execute.", "text-gray-500");
