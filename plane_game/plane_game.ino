/*
  =====================================================================
  ESP32 + MPU6050  ->  Tilt-Controlled "Web Plane Game"
  =====================================================================

  WHAT THIS DOES
  ---------------------------------------------------------------------
  - ESP32 connects to your WiFi and hosts a web page (a canvas plane game).
  - MPU6050 is read continuously over I2C (no external MPU6050 library
    needed - raw register access, so you only need two libraries).
  - Tilt data is streamed to the browser over a WebSocket (port 81).
  - You tilt the ESP32+MPU6050 board forward/back (pitch) to climb and
    dive your plane through gaps in oncoming obstacles. Up/Down arrow
    keys work too, for testing without hardware.

  WIRING (ESP32 default I2C pins)
  ---------------------------------------------------------------------
    MPU6050        ESP32
    -----------------------
    VCC     ->     3.3V
    GND     ->     GND
    SCL     ->     GPIO 22
    SDA     ->     GPIO 21

  LIBRARIES TO INSTALL (Arduino IDE Library Manager)
  ---------------------------------------------------------------------
    1) "WebSockets" by Markus Sattler (Links2004/arduinoWebSockets)
       -> used for the real-time tilt-data stream to the browser
    (Wire.h, WiFi.h, WebServer.h are built into the ESP32 core already)

  BOARD
  ---------------------------------------------------------------------
    Tools > Board > ESP32 Dev Module (or your specific ESP32 board)

  HOW TO USE
  ---------------------------------------------------------------------
    1) Fill in WIFI_SSID / WIFI_PASSWORD below.
    2) Upload the sketch, open Serial Monitor at 115200 baud.
    3) Note the printed IP address.
    4) On a phone/laptop on the same WiFi, open http://<that-ip>/
    5) Tilt the ESP32 board left/right to steer the car!
  =====================================================================
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <WebSocketsServer.h>

// ---------------------- USER CONFIG ---------------------------------
const char *WIFI_SSID     = "12";
const char *WIFI_PASSWORD = "12345678";

#define SDA_PIN 21
#define SCL_PIN 22
#define MPU_ADDR 0x68

// ---------------------- GLOBALS ---------------------------------------
WebServer      server(80);
WebSocketsServer webSocket(81);

float accX, accY, accZ;      // g's
float gyroX, gyroY, gyroZ;   // deg/s
float gyroOffX = 0, gyroOffY = 0, gyroOffZ = 0;

unsigned long lastSend = 0;
const unsigned long SEND_INTERVAL_MS = 40; // ~25Hz stream to browser

// ======================================================================
//                          MPU6050 LOW-LEVEL I2C
// ======================================================================
void mpuWriteReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool mpuReadBytes(uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((int)MPU_ADDR, (int)len, (int)true);
  for (uint8_t i = 0; i < len && Wire.available(); i++) {
    buf[i] = Wire.read();
  }
  return true;
}

void mpuInit() {
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  mpuWriteReg(0x6B, 0x00); // PWR_MGMT_1: wake up (clear sleep bit)
  delay(100);
  mpuWriteReg(0x1C, 0x00); // ACCEL_CONFIG: +-2g
  mpuWriteReg(0x1B, 0x00); // GYRO_CONFIG:  +-250 deg/s
  delay(50);
}

// quick startup calibration - keep the board still while this runs
void mpuCalibrateGyro() {
  const int N = 200;
  long sx = 0, sy = 0, sz = 0;
  uint8_t raw[14];
  for (int i = 0; i < N; i++) {
    if (mpuReadBytes(0x3B, raw, 14)) {
      int16_t gx = (raw[8]  << 8) | raw[9];
      int16_t gy = (raw[10] << 8) | raw[11];
      int16_t gz = (raw[12] << 8) | raw[13];
      sx += gx; sy += gy; sz += gz;
    }
    delay(3);
  }
  gyroOffX = (sx / (float)N) / 131.0;
  gyroOffY = (sy / (float)N) / 131.0;
  gyroOffZ = (sz / (float)N) / 131.0;
}

void mpuRead() {
  uint8_t raw[14];
  if (!mpuReadBytes(0x3B, raw, 14)) return;

  int16_t axr = (raw[0]  << 8) | raw[1];
  int16_t ayr = (raw[2]  << 8) | raw[3];
  int16_t azr = (raw[4]  << 8) | raw[5];
  // raw[6],raw[7] = temperature, unused
  int16_t gxr = (raw[8]  << 8) | raw[9];
  int16_t gyr = (raw[10] << 8) | raw[11];
  int16_t gzr = (raw[12] << 8) | raw[13];

  accX = axr / 16384.0;
  accY = ayr / 16384.0;
  accZ = azr / 16384.0;

  gyroX = (gxr / 131.0) - gyroOffX;
  gyroY = (gyr / 131.0) - gyroOffY;
  gyroZ = (gzr / 131.0) - gyroOffZ;
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
<title>Tilt Plane - ESP32 MPU6050</title>
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
  <h2>Tilt Plane</h2>
  <div id="hud">
    <span>Score: <b id="score">0</b></span>
    <span>Speed: <b id="speed">0</b></span>
    <span>Tilt: <b id="tiltval">0.0</b></span>
  </div>
  <div id="container">
    <canvas id="game" width="380" height="540"></canvas>
    <div id="overlay">
      <h1 id="overlayTitle">Tilt Plane</h1>
      <p>Tilt the ESP32 board forward/back (or left/right, depending on<br>
      how you hold it) to climb and dive through the gaps.<br>(Up/Down arrow keys also work for testing.)</p>
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
const tiltEl = document.getElementById('tiltval');
const overlay = document.getElementById('overlay');
const overlayTitle = document.getElementById('overlayTitle');
const startBtn = document.getElementById('startBtn');

// ---------------- WebSocket connection to ESP32 ----------------
let tiltY = 0;           // smoothed pitch input, roughly -1..1 (neg = climb, pos = dive)
let rawAccY = 0;
let wsConnected = false;

function connectWS(){
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.hostname + ':81/');
  ws.onopen = () => { wsConnected = true; statusEl.textContent = 'MPU6050 connected'; statusEl.className='ok'; };
  ws.onclose = () => { wsConnected = false; statusEl.textContent = 'disconnected - retrying...'; statusEl.className='bad'; setTimeout(connectWS, 1500); };
  ws.onerror = () => { ws.close(); };
  ws.onmessage = (evt) => {
    try {
      const d = JSON.parse(evt.data);
      // Steer using accelerometer Y (tilt forward/back = pitch). Clamp & scale.
      rawAccY = d.ay;
      let v = d.ay * 1.1;             // sensitivity (lower = gentler control)
      if (v > 1) v = 1; if (v < -1) v = -1;
      tiltY = tiltY * 0.85 + v * 0.15; // smoothing (higher = steadier flight)
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

function spawnObstacle(){
  const gap = Math.max(310 - speed*2.5, 160);
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

  // combine tilt input + keyboard fallback -> vertical velocity
  let pitch = tiltY;
  if (keyUp) pitch = -1;
  if (keyDown) pitch = 1;

  const maxClimbSpeed = 4.0;
  plane.vy = plane.vy * 0.8 + (pitch * maxClimbSpeed) * 0.2;
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
  tiltEl.textContent = rawAccY.toFixed(2);
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

  // simple scrolling clouds
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
    // top bar
    ctx.fillRect(o.x, 0, o.w, o.gapY);
    // bottom bar
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

  // fuselage
  ctx.fillStyle = '#ecf0f1';
  ctx.beginPath();
  ctx.moveTo(-plane.w/2, 0);
  ctx.lineTo(plane.w/2 - 8, -plane.h/2 + 4);
  ctx.lineTo(plane.w/2, 0);
  ctx.lineTo(plane.w/2 - 8, plane.h/2 - 4);
  ctx.closePath();
  ctx.fill();

  // tail wing
  ctx.fillStyle = '#e74c3c';
  ctx.beginPath();
  ctx.moveTo(-plane.w/2, 0);
  ctx.lineTo(-plane.w/2 + 10, -plane.h/2);
  ctx.lineTo(-plane.w/2 + 16, 0);
  ctx.closePath();
  ctx.fill();

  // main wing
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

  // cockpit
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

startBtn.addEventListener('click', () => {
  overlay.style.display = 'none';
  overlayTitle.textContent = 'Tilt Plane';
  resetGame();
});

resetGame();
running = false; // wait for Start button
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
  Serial.println("Booting Tilt Car server...");

  mpuInit();
  Serial.println("Calibrating gyro - keep the board still...");
  mpuCalibrateGyro();
  Serial.println("Calibration done.");

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

  mpuRead();

  unsigned long now = millis();
  if (now - lastSend >= SEND_INTERVAL_MS) {
    lastSend = now;
    char json[160];
    snprintf(json, sizeof(json),
      "{\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.2f,\"gy\":%.2f,\"gz\":%.2f}",
      accX, accY, accZ, gyroX, gyroY, gyroZ);
    webSocket.broadcastTXT(json);
  }
}
