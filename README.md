# ESP32 + MPU6050 Tilt-Controlled Car Racing Game (WiFi)

Tilt karke apne laptop pe car racing game khelo — ESP32 aur MPU6050
sensor aapke tilt movement ko WiFi (UDP) ke through laptop tak
bhejte hain.

## Kya chahiye (Hardware)
- ESP32 Dev Board
- MPU6050 sensor module
- Jumper wires
- Laptop (WiFi se ESP32 wale hi network se connected)

## Wiring
| MPU6050 Pin | ESP32 Pin |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SCL | GPIO 22 |
| SDA | GPIO 21 |

## Step-by-Step Setup

### 1. Arduino IDE Setup (ESP32 side)
1. Arduino IDE me ESP32 board support install karo (agar pehle se nahi hai):
   `File -> Preferences -> Additional Board URLs` me daalo:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   Fir `Tools -> Board -> Boards Manager` me "esp32" search karke install karo.
2. Yeh libraries install karo (`Tools -> Manage Libraries`):
   - `Adafruit MPU6050`
   - `Adafruit Unified Sensor`
3. `esp32_mpu6050_wifi_sender.ino` file kholo.
4. Isme yeh 3 cheezein apni info se badlo:
   - `WIFI_SSID` -> apna WiFi naam
   - `WIFI_PASSWORD` -> apna WiFi password
   - `LAPTOP_IP` -> apne laptop ka local IP address (neeche step 3 dekho)
5. ESP32 ko USB se connect karo, sahi Board + Port select karo, aur Upload kar do.
6. Serial Monitor (115200 baud) kholo — dekho ki WiFi connect ho gaya
   aur "Calibrating..." message aaye to device ko 2 second seedha (flat) rakho.

### 2. Laptop ka IP address pata karo
- **Windows**: Command Prompt me `ipconfig` chalao -> "IPv4 Address" dekho (jaise `192.168.1.5`)
- **Mac/Linux**: Terminal me `ifconfig` ya `ip addr` chalao -> apne WiFi interface ka IP dekho

Yeh IP `esp32_mpu6050_wifi_sender.ino` ke `LAPTOP_IP` variable me daalna hai.

> ⚠️ Important: ESP32 aur laptop DONO same WiFi network par hone chahiye
> (jaise dono ek hi ghar ke WiFi router se connected).

### 3. Python Game Setup (Laptop side)
1. Python 3.8+ installed hona chahiye.
2. Terminal/Command Prompt me project folder me jao aur chalao:
   ```
   pip install -r requirements.txt
   ```
3. Game chalao:
   ```
   python car_racing_game.py
   ```
4. Ek window khulegi jisme "ESP32: Waiting..." dikhega. Jaise hi ESP32
   se data aana shuru hoga, wo "ESP32: Connected" ho jaayega aur
   MPU6050 tilt se car move hone lagegi.

## Controls
- MPU6050 ko left/right tilt karo -> Car left/right move hogi.
- Sensor connect na ho to Left/Right Arrow keys se test kar sakte ho.
- `R` -> Restart (game over hone ke baad)
- `ESC` ya window close -> Exit

## Troubleshooting
- **"ESP32: Waiting..." hi dikh raha hai, connect nahi ho raha**
  - Firewall check karo — pehli baar Python chalane par ek popup aata
    hai "Allow access", usko Allow karo (especially Windows Defender Firewall).
  - Confirm karo ki `LAPTOP_IP` (ESP32 code me) aur laptop ka actual IP
    same hai.
  - Confirm karo ki ESP32 aur laptop same WiFi network par hain
    (mobile hotspot use kar rahe ho to dono usi hotspot se connected hone chahiye).
  - Router ka "AP/Client Isolation" setting off honi chahiye (kai routers
    me yeh setting devices ko ek doosre se baat karne se rokti hai).
- **Car bahut sensitive/jyada tez move ho rahi hai**
  - `car_racing_game.py` me `TILT_SENSITIVITY` value kam kar do (jaise 6.0 -> 3.5).
- **MPU6050 mila hi nahi (ESP32 Serial Monitor me error)**
  - Wiring dobara check karo, especially SDA/SCL pins.
- **IP address change ho jaata hai baar baar**
  - Apne WiFi router settings me ESP32 ke liye "Static IP" / "DHCP
    reservation" laptop ke liye bhi set kar sakte ho taaki IP fix rahe.

## Files
- `esp32_mpu6050_wifi_sender.ino` — ESP32 firmware (Arduino code)
- `car_racing_game.py` — Laptop pe chalne wala game (Python + Pygame)
- `requirements.txt` — Python dependencies
