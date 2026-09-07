/*
  =====================================================================
  ESP32 + Analog Joystick  ->  Web-Hosted "Tilt Plane" Game
  =====================================================================

  WHAT THIS DOES
  ---------------------------------------------------------------------
  - ESP32 connects to your WiFi and hosts a web page (a canvas plane
    game - same game as the MPU6050 version, but now controlled by a
    standard 2-axis analog joystick module instead of a tilt sensor).
  - Joystick X/Y (and the built-in push-button, if your module has one)
    are read continuously and streamed to the browser over a WebSocket
    (port 81).
  - Push the joystick up/down to climb/dive your plane through gaps in
    oncoming obstacles. Push the button (or click Start) to begin /
    restart. Up/Down arrow keys also work, for testing without hardware.

  WIRING (typical KY-023 / PS2-style analog joystick module)
  ---------------------------------------------------------------------
    Joystick       ESP32
    -----------------------
    VCC     ->     3.3V
    GND     ->     GND
    VRx     ->     GPIO 34   (ADC1_CH6, analog X axis)
    VRy     ->     GPIO 35   (ADC1_CH7, analog Y axis)
    SW      ->     GPIO 32   (digital push-button, active LOW,
                              uses internal pull-up - optional)

    NOTE: GPIO34/35 are input-only, ADC1 pins - perfect for analog
    reads and don't clash with WiFi (which uses ADC2 internally).

  LIBRARIES TO INSTALL (Arduino IDE Library Manager)
  ---------------------------------------------------------------------
    1) "WebSockets" by Markus Sattler (Links2004/arduinoWebSockets)
       -> used for the real-time joystick-data stream to the browser
    (WiFi.h and WebServer.h are built into the ESP32 core already)

  BOARD
  ---------------------------------------------------------------------
    Tools > Board > ESP32 Dev Module (or your specific ESP32 board)

  HOW TO USE
  ---------------------------------------------------------------------
    1) Fill in WIFI_SSID / WIFI_PASSWORD below.
    2) Upload the sketch, open Serial Monitor at 115200 baud.
    3) Note the printed IP address. Keep the joystick centered/still
       while it boots - it auto-calibrates the center position.
    4) On a phone/laptop on the same WiFi, open http://<that-ip>/
    5) Push the joystick up/down to climb and dive your plane!
  =====================================================================
*/

#include <WiFi.h>
#include <WebServer.h>
#include <WebSocketsServer.h>

// ---------------------- USER CONFIG ---------------------------------
const char *WIFI_SSID     = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

#define VRX_PIN 34
#define VRY_PIN 35
#define SW_PIN  32   // set to -1 if your joystick module has no button

// ---------------------- GLOBALS ---------------------------------------
WebServer        server(80);
WebSocketsServer webSocket(81);

int centerX = 2048, centerY = 2048; // auto-calibrated at boot
float joyX = 0, joyY = 0;           // normalized -1..1
bool  buttonPressed = false;

unsigned long lastSend = 0;
const unsigned long SEND_INTERVAL_MS = 40; // ~25Hz stream to browser

// ======================================================================
//                          JOYSTICK READING
// ======================================================================
void joystickInit() {
  pinMode(VRX_PIN, INPUT);
  pinMode(VRY_PIN, INPUT);
  if (SW_PIN >= 0) pinMode(SW_PIN, INPUT_PULLUP);

  analogReadResolution(12);          // 0-4095
  analogSetAttenuation(ADC_11db);    // full 0-3.3V range

  // Average a bunch of samples to find the resting center of the stick.
  // Keep the joystick untouched while this runs.
  long sx = 0, sy = 0;
  const int N = 100;
  for (int i = 0; i < N; i++) {
    sx += analogRead(VRX_PIN);
    sy += analogRead(VRY_PIN);
    delay(3);
  }
  centerX = sx / N;
  centerY = sy / N;
}

void joystickRead() {
  int rx = analogRead(VRX_PIN);
  int ry = analogRead(VRY_PIN);

  // Normalize around the calibrated center to roughly -1..1.
  float nx = (rx - centerX) / 2048.0;
  float ny = (ry - centerY) / 2048.0;

  if (nx > 1) nx = 1; if (nx < -1) nx = -1;
  if (ny > 1) ny = 1; if (ny < -1) ny = -1;

  // small deadzone so the plane doesn't drift when the stick is "centered"
  const float DEADZONE = 0.06;
  if (fabs(nx) < DEADZONE) nx = 0;
  if (fabs(ny) < DEADZONE) ny = 0;

  joyX = nx;
  joyY = ny;

  buttonPressed = (SW_PIN >= 0) ? (digitalRead(SW_PIN) == LOW) : false;
}

// ======================================================================
//                          WEBSOCKET EVENTS
// ======================================================================
void onWebSocketEvent(uint8_t num, WStype_t type, uint8_t *payload, size_t length) {
  if (type == WStype_CONNECTED) {
    Serial.printf("[WS] Client #%u connected\n", num);
  } else if (type == WStype_DISCONNECTED) {
    Serial.printf("[WS] Client #%u disconnected\n", num);
  }
  // We don't need to handle incoming messages from the browser for this game.
}

// ======================================================================
//                          HTML / JS / CSS  (served at "/")
// ======================================================================
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Joystick Plane - ESP32</title>
<style>
  html,body{margin:0;padding:0;background:#111;color:#eee;font-family:sans-serif;overflow:hidden;height:100%;}
  #wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;}
  canvas{background:#2b2b2b;border:3px solid #444;border-radius:8px;touch-action:none;}
  #hud{display:flex;gap:20px;margin:8px 0;font-size:14px;}
  #hud span{background:#222;padding:4px 10px;border-radius:6px;border:1px solid #444;}
  #status{position:fixed;top:6px;left:6px;font-size:12px;padding:3px 8px;border-radius:5px;}
  .ok{background:#164;color:#8f8;}
  .bad{background:#611;color:#f88;}
  #overlay{position:absolute;top:0;left:0;width:100%;height:100%;display:flex;flex-direction:column;
    align-items:center;justify-content:center;background:rgba(0,0,0,0.75);text-align:center;}
  #overlay h1{margin:0 0 8px 0;}
  button{background:#2a7;color:#fff;border:none;padding:10px 22px;font-size:16px;border-radius:6px;cursor:pointer;margin-top:10px;}
  button:hover{background:#3c8;}
  #container{position:relative;}
</style>
</head>
<body>
<div id="status" class="bad">connecting...</div>
<div id="wrap">
  <h2>Joystick Plane</h2>
  <div id="hud">
    <span>Score: <b id="score">0</b></span>
    <span>Speed: <b id="speed">0</b></span>
    <span>Stick Y: <b id="joyval">0.0</b></span>
  </div>
  <div id="container">
    <canvas id="game" width="380" height="540"></canvas>
    <div id="overlay">
      <h1 id="overlayTitle">Joystick Plane</h1>
      <p>Push the joystick up/down to climb and dive through the gaps.<br>
      Press the joystick button (or click Start) to play.<br>(Up/Down arrow keys also work for testing.)</p>
      <button id="startBtn">Start Game</button>
    </div>
  </div>
</div>

<script>
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const W = canvas.width, H = canvas.height;

const statusEl = document.getElementById('status');
const scoreEl = document.getElementById('score');
const speedEl = document.getElementById('speed');
const joyEl = document.getElementById('joyval');
const overlay = document.getElementById('overlay');
const overlayTitle = document.getElementById('overlayTitle');
const startBtn = document.getElementById('startBtn');

// ---------------- WebSocket connection to ESP32 ----------------
let stickY = 0;          // smoothed vertical input, roughly -1..1
let rawJoyY = 0;
let buttonDown = false;
let prevButtonDown = false;
let wsConnected = false;

function connectWS(){
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.hostname + ':81/');
  ws.onopen = () => { wsConnected = true; statusEl.textContent = 'Joystick connected'; statusEl.className='ok'; };
  ws.onclose = () => { wsConnected = false; statusEl.textContent = 'disconnected - retrying...'; statusEl.className='bad'; setTimeout(connectWS, 1500); };
  ws.onerror = () => { ws.close(); };
  ws.onmessage = (evt) => {
    try {
      const d = JSON.parse(evt.data);
      rawJoyY = d.y;
      let v = d.y * 1.3;              // sensitivity
      if (v > 1) v = 1; if (v < -1) v = -1;
      stickY = stickY * 0.7 + v * 0.3; // smoothing (direct stick, less lag than tilt)

      prevButtonDown = buttonDown;
      buttonDown = !!d.btn;
      if (buttonDown && !prevButtonDown && !running) {
        startGame();
      }
    } catch(e) {}
  };
}
connectWS();

// ---------------- Keyboard fallback (for testing without hardware) ----------------
let keyUp = false, keyDown = false;
window.addEventListener('keydown', e=>{
  if(e.key === 'ArrowUp') keyUp = true;
  if(e.key === 'ArrowDown') keyDown = true;
});
window.addEventListener('keyup', e=>{
  if(e.key === 'ArrowUp') keyUp = false;
  if(e.key === 'ArrowDown') keyDown = false;
});

// ================= GAME STATE =================
const planeX = 70;
const planeW = 46, planeH = 26;

let plane, obstacles, particles, score, speed, running, spawnTimer;

function resetGame(){
  plane = { y: H/2 - planeH/2, w: planeW, h: planeH, vy: 0 };
  obstacles = [];
  particles = [];
  score = 0;
  speed = 2.2;
  running = true;
  spawnTimer = 0;
}

function startGame(){
  overlay.style.display = 'none';
  overlayTitle.textContent = 'Joystick Plane';
  resetGame();
}

function spawnObstacle(){
  const gap = Math.max(210 - speed*2.5, 160);
  const gapY = 40 + Math.random() * (H - 80 - gap);
  obstacles.push({
    x: W + 30,
    gapY: gapY,
    gapH: gap,
    w: 46,
    passed: false
  });
}

function update(){
  if(!running) return;

  // combine joystick input + keyboard fallback -> vertical velocity
  // note: pushing joystick UP typically reads as negative Y -> plane climbs (negative = up on screen)
  let pitch = stickY;
  if (keyUp) pitch = -1;
  if (keyDown) pitch = 1;

  const maxClimbSpeed = 4.4;
  plane.vy = plane.vy * 0.78 + (pitch * maxClimbSpeed) * 0.22;
  plane.y += plane.vy;

  if (plane.y < 0) { plane.y = 0; plane.vy = 0; }
  if (plane.y + plane.h > H) { plane.y = H - plane.h; plane.vy = 0; }

  // engine trail particles
  particles.push({x: planeX, y: plane.y + plane.h/2 + (Math.random()*8-4), r: 3+Math.random()*2, life: 20});
  particles.forEach(p => { p.x -= speed*1.2; p.life--; });
  particles = particles.filter(p => p.life > 0 && p.x > -10);

  speed += 0.0010;
  score += speed * 0.05;

  spawnTimer -= speed;
  if (spawnTimer <= 0){
    spawnObstacle();
    spawnTimer = 100 - Math.min(speed*3, 30) + Math.random()*30;
  }

  for (let i = obstacles.length-1; i>=0; i--){
    const o = obstacles[i];
    o.x -= speed;
    if (o.x + o.w < -10) { obstacles.splice(i,1); continue; }

    if (!o.passed && o.x + o.w < planeX) {
      o.passed = true;
      score += 10;
    }

    // forgiving hitbox: shrink the plane's collision box a bit so
    // close calls don't feel like unfair crashes
    const inset = 7;
    const planeRight = planeX + plane.w - inset;
    const planeLeft = planeX + inset;
    const hitsColumn = planeRight > o.x && planeLeft < o.x + o.w;
    if (hitsColumn) {
      const hitsTopBar = plane.y + inset < o.gapY;
      const hitsBottomBar = plane.y + plane.h - inset > o.gapY + o.gapH;
      if (hitsTopBar || hitsBottomBar) gameOver();
    }
  }

  scoreEl.textContent = Math.floor(score);
  speedEl.textContent = speed.toFixed(1);
  joyEl.textContent = rawJoyY.toFixed(2);
}

function gameOver(){
  running = false;
  overlayTitle.textContent = 'Crashed! Score: ' + Math.floor(score);
  startBtn.textContent = 'Try Again';
  overlay.style.display = 'flex';
}

function drawSky(){
  const grad = ctx.createLinearGradient(0,0,0,H);
  grad.addColorStop(0, '#1b3a5c');
  grad.addColorStop(1, '#0d1f33');
  ctx.fillStyle = grad;
  ctx.fillRect(0,0,W,H);

  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  for (let i=0;i<5;i++){
    const cx = ((i*140) - (Date.now()/40 % 140) + W) % (W+140) - 70;
    const cy = 60 + i*90 % (H-100);
    ctx.beginPath();
    ctx.ellipse(cx, cy, 40, 16, 0, 0, Math.PI*2);
    ctx.fill();
  }
}

function drawObstacles(){
  obstacles.forEach(o=>{
    ctx.fillStyle = '#6fcf97';
    ctx.fillRect(o.x, 0, o.w, o.gapY);
    ctx.fillRect(o.x, o.gapY + o.gapH, o.w, H - (o.gapY+o.gapH));
    ctx.fillStyle = 'rgba(0,0,0,0.2)';
    ctx.fillRect(o.x, o.gapY-8, o.w, 8);
    ctx.fillRect(o.x, o.gapY+o.gapH, o.w, 8);
  });
}

function drawParticles(){
  particles.forEach(p=>{
    ctx.fillStyle = `rgba(255,200,80,${p.life/20})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
    ctx.fill();
  });
}

function drawPlane(){
  ctx.save();
  ctx.translate(planeX + plane.w/2, plane.y + plane.h/2);
  ctx.rotate(plane.vy * 0.08);

  ctx.fillStyle = '#ecf0f1';
  ctx.beginPath();
  ctx.moveTo(-plane.w/2, 0);
  ctx.lineTo(plane.w/2 - 8, -plane.h/2 + 4);
  ctx.lineTo(plane.w/2, 0);
  ctx.lineTo(plane.w/2 - 8, plane.h/2 - 4);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = '#e74c3c';
  ctx.beginPath();
  ctx.moveTo(-plane.w/2, 0);
  ctx.lineTo(-plane.w/2 + 10, -plane.h/2);
  ctx.lineTo(-plane.w/2 + 16, 0);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = '#3498db';
  ctx.beginPath();
  ctx.moveTo(-4, -3);
  ctx.lineTo(6, -plane.h/2 - 6);
  ctx.lineTo(14, -plane.h/2 - 6);
  ctx.lineTo(6, -3);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(-4, 3);
  ctx.lineTo(6, plane.h/2 + 6);
  ctx.lineTo(14, plane.h/2 + 6);
  ctx.lineTo(6, 3);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = '#2c3e50';
  ctx.beginPath();
  ctx.arc(4, 0, 4, 0, Math.PI*2);
  ctx.fill();

  ctx.restore();
}

function draw(){
  drawSky();
  drawParticles();
  drawObstacles();
  drawPlane();
}

function loop(){
  update();
  draw();
  requestAnimationFrame(loop);
}

startBtn.addEventListener('click', startGame);

resetGame();
running = false; // wait for Start button / joystick press
draw();
requestAnimationFrame(loop);
</script>
</body>
</html>
)rawliteral";

// ======================================================================
//                          HTTP HANDLERS
// ======================================================================
void handleRoot() {
  server.send_P(200, "text/html", INDEX_HTML);
}

void handleNotFound() {
  server.send(404, "text/plain", "Not found");
}

// ======================================================================
//                          SETUP / LOOP
// ======================================================================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("Booting Joystick Plane server...");

  Serial.println("Calibrating joystick center - keep it untouched...");
  joystickInit();
  Serial.printf("Calibration done. Center = (%d, %d)\n", centerX, centerY);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected! IP address: ");
  Serial.println(WiFi.localIP());
  Serial.println("Open this address in a browser on the same network.");

  server.on("/", handleRoot);
  server.onNotFound(handleNotFound);
  server.begin();

  webSocket.begin();
  webSocket.onEvent(onWebSocketEvent);

  Serial.println("HTTP server started on port 80");
  Serial.println("WebSocket server started on port 81");
}

void loop() {
  server.handleClient();
  webSocket.loop();

  joystickRead();

  unsigned long now = millis();
  if (now - lastSend >= SEND_INTERVAL_MS) {
    lastSend = now;
    char json[96];
    snprintf(json, sizeof(json),
      "{\"x\":%.3f,\"y\":%.3f,\"btn\":%d}",
      joyX, joyY, buttonPressed ? 1 : 0);
    webSocket.broadcastTXT(json);
  }
}
