/*
  ================================================================
        ESP32 + MPU6050 + WiFi + UDP
        DIRECT I2C VERSION
  ================================================================

  MPU6050:
  VCC -> 3.3V
  GND -> GND
  SDA -> GPIO 21
  SCL -> GPIO 22

  MPU6050 Address:
  0x68

  UDP Port:
  4210

  IMPORTANT:
  LAPTOP_IP ko apne laptop ke IPv4 address se change karo.

  This code DOES NOT use Adafruit MPU6050 library.
  MPU6050 is controlled directly through I2C registers.
  ================================================================
*/

#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>


// ================================================================
// I2C
// ================================================================

#define SDA_PIN 21
#define SCL_PIN 22

#define MPU_ADDR 0x68


// ================================================================
// WIFI
// ================================================================

const char* WIFI_SSID = "12";
const char* WIFI_PASSWORD = "12345678";

const char* LAPTOP_IP = "10.181.150.196";

const int UDP_PORT = 4210;


// ================================================================
// UDP
// ================================================================

WiFiUDP udp;


// ================================================================
// CALIBRATION
// ================================================================

float rollOffset = 0.0;


// ================================================================
// MPU6050 REGISTERS
// ================================================================

#define WHO_AM_I_REG       0x75
#define PWR_MGMT_1_REG     0x6B
#define SMPLRT_DIV_REG     0x19
#define CONFIG_REG         0x1A
#define GYRO_CONFIG_REG    0x1B
#define ACCEL_CONFIG_REG   0x1C
#define ACCEL_XOUT_H_REG   0x3B


// ================================================================
// I2C WRITE
// ================================================================

void writeRegister(byte reg, byte value) {

  Wire.beginTransmission(MPU_ADDR);

  Wire.write(reg);

  Wire.write(value);

  byte error = Wire.endTransmission();

  if (error != 0) {

    Serial.print("I2C Write Error: ");
    Serial.println(error);
  }
}


// ================================================================
// I2C READ
// ================================================================

byte readRegister(byte reg) {

  Wire.beginTransmission(MPU_ADDR);

  Wire.write(reg);

  byte error = Wire.endTransmission(false);

  if (error != 0) {

    Serial.print("I2C Read Error: ");
    Serial.println(error);

    return 0;
  }

  Wire.requestFrom(MPU_ADDR, (uint8_t)1);

  if (Wire.available()) {

    return Wire.read();
  }

  return 0;
}


// ================================================================
// READ 14 BYTES FROM MPU6050
// ================================================================

bool readMPU(
  int16_t &accelX,
  int16_t &accelY,
  int16_t &accelZ,
  int16_t &gyroX,
  int16_t &gyroY,
  int16_t &gyroZ,
  int16_t &temperature
) {

  Wire.beginTransmission(MPU_ADDR);

  Wire.write(ACCEL_XOUT_H_REG);

  byte error = Wire.endTransmission(false);

  if (error != 0) {

    return false;
  }

  uint8_t received = Wire.requestFrom(
    MPU_ADDR,
    (uint8_t)14,
    (uint8_t)true
  );

  if (received != 14) {

    return false;
  }


  // Accelerometer

  accelX = (Wire.read() << 8) | Wire.read();

  accelY = (Wire.read() << 8) | Wire.read();

  accelZ = (Wire.read() << 8) | Wire.read();


  // Temperature

  temperature = (Wire.read() << 8) | Wire.read();


  // Gyroscope

  gyroX = (Wire.read() << 8) | Wire.read();

  gyroY = (Wire.read() << 8) | Wire.read();

  gyroZ = (Wire.read() << 8) | Wire.read();


  return true;
}


// ================================================================
// CHECK MPU6050
// ================================================================

bool checkMPU() {

  Serial.println();
  Serial.println("Checking MPU6050...");


  // Check I2C address

  Wire.beginTransmission(MPU_ADDR);

  byte error = Wire.endTransmission();


  if (error != 0) {

    Serial.println("ERROR: Device at 0x68 not responding!");

    return false;
  }


  Serial.println("I2C device found at 0x68");


  // Read WHO_AM_I

  byte whoAmI = readRegister(WHO_AM_I_REG);


  Serial.print("WHO_AM_I = 0x");

  if (whoAmI < 16) {
    Serial.print("0");
  }

  Serial.println(whoAmI, HEX);


  /*
    Normal MPU6050:
    WHO_AM_I = 0x68
  */


  if (whoAmI == 0x68) {

    Serial.println("MPU6050 identity OK!");

  } else {

    Serial.println();
    Serial.println("WARNING:");
    Serial.println("Device is responding at 0x68");
    Serial.println("but WHO_AM_I is not 0x68.");

    Serial.println("Continuing anyway...");
  }


  return true;
}


// ================================================================
// INITIALIZE MPU6050
// ================================================================

void initializeMPU() {

  Serial.println();
  Serial.println("Initializing MPU6050 registers...");


  // Wake up MPU6050

  writeRegister(
    PWR_MGMT_1_REG,
    0x00
  );

  delay(100);


  // Sample rate

  writeRegister(
    SMPLRT_DIV_REG,
    0x04
  );


  // Digital Low Pass Filter

  writeRegister(
    CONFIG_REG,
    0x03
  );


  // Gyroscope +/-500 deg/s

  writeRegister(
    GYRO_CONFIG_REG,
    0x08
  );


  // Accelerometer +/-8G

  writeRegister(
    ACCEL_CONFIG_REG,
    0x10
  );


  delay(100);


  Serial.println("MPU6050 registers initialized!");

}


// ================================================================
// CALCULATE ROLL
// ================================================================

float getRollAngle() {

  int16_t ax;
  int16_t ay;
  int16_t az;

  int16_t gx;
  int16_t gy;
  int16_t gz;

  int16_t temperature;


  if (!readMPU(
        ax,
        ay,
        az,
        gx,
        gy,
        gz,
        temperature
      )) {

    Serial.println("MPU read failed!");

    return 0.0;
  }


  /*
    Accelerometer sensitivity for +/-8G:

    4096 LSB/G
  */

  float accelX = ax / 4096.0;

  float accelY = ay / 4096.0;

  float accelZ = az / 4096.0;


  // Calculate roll

  float roll =
    atan2(
      accelY,
      accelZ
    ) * 180.0 / PI;


  return roll;
}


// ================================================================
// CALIBRATION
// ================================================================

void calibrateMPU() {

  Serial.println();
  Serial.println("================================");
  Serial.println("       MPU CALIBRATION");
  Serial.println("================================");

  Serial.println();

  Serial.println("Keep MPU6050 FLAT.");
  Serial.println("Do NOT move it.");

  delay(3000);


  float total = 0.0;

  int validSamples = 0;


  Serial.println("Taking 100 samples...");


  for (int i = 0; i < 100; i++) {

    float angle = getRollAngle();

    total += angle;

    validSamples++;

    delay(10);
  }


  if (validSamples > 0) {

    rollOffset = total / validSamples;
  }


  Serial.println();

  Serial.print("Roll Offset = ");

  Serial.print(rollOffset, 2);

  Serial.println(" degrees");

  Serial.println();

  Serial.println("Calibration complete!");

}


// ================================================================
// WIFI CONNECTION
// ================================================================

void connectWiFi() {

  Serial.println();
  Serial.println("================================");
  Serial.println("          WIFI");
  Serial.println("================================");


  WiFi.mode(WIFI_STA);

  WiFi.setSleep(false);

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );


  Serial.print("Connecting");


  int attempts = 0;


  while (WiFi.status() != WL_CONNECTED) {

    delay(500);

    Serial.print(".");

    attempts++;


    if (attempts >= 40) {

      Serial.println();

      Serial.println("WiFi connection failed!");

      Serial.println("Restarting WiFi...");


      WiFi.disconnect();

      delay(1000);

      WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD
      );

      attempts = 0;
    }
  }


  Serial.println();

  Serial.println();

  Serial.println("WiFi CONNECTED!");

  Serial.print("ESP32 IP: ");

  Serial.println(
    WiFi.localIP()
  );


  Serial.print("Laptop IP: ");

  Serial.println(
    LAPTOP_IP
  );


  Serial.print("UDP Port: ");

  Serial.println(
    UDP_PORT
  );


  udp.begin(UDP_PORT);

}


// ================================================================
// SETUP
// ================================================================

void setup() {

  Serial.begin(115200);

  delay(1000);


  Serial.println();
  Serial.println();
  Serial.println("======================================");
  Serial.println(" ESP32 MPU6050 TILT CONTROLLER");
  Serial.println("======================================");


  // ==============================================================
  // I2C
  // ==============================================================

  Serial.println();

  Serial.println("Starting I2C...");


  Wire.begin(
    SDA_PIN,
    SCL_PIN
  );


  Wire.setClock(100000);


  delay(500);


  Serial.print("SDA: GPIO ");

  Serial.println(SDA_PIN);


  Serial.print("SCL: GPIO ");

  Serial.println(SCL_PIN);


  // ==============================================================
  // CHECK MPU
  // ==============================================================

  if (!checkMPU()) {

    Serial.println();

    Serial.println("MPU6050 NOT FOUND!");

    while (true) {

      delay(2000);

      Serial.println(
        "Waiting for MPU6050..."
      );
    }
  }


  // ==============================================================
  // INITIALIZE MPU
  // ==============================================================

  initializeMPU();


  // ==============================================================
  // TEST SENSOR
  // ==============================================================

  Serial.println();

  Serial.println("Testing sensor...");


  for (int i = 0; i < 5; i++) {

    float angle = getRollAngle();


    Serial.print(
      "Test Roll = "
    );

    Serial.print(
      angle,
      2
    );

    Serial.println(
      " degrees"
    );


    delay(500);
  }


  // ==============================================================
  // CALIBRATION
  // ==============================================================

  calibrateMPU();


  // ==============================================================
  // WIFI
  // ==============================================================

  connectWiFi();


  // ==============================================================
  // READY
  // ==============================================================

  Serial.println();

  Serial.println("======================================");

  Serial.println("          SYSTEM READY!");

  Serial.println("======================================");

  Serial.println();

}


// ================================================================
// LOOP
// ================================================================

void loop() {


  // ==============================================================
  // WIFI CHECK
  // ==============================================================

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println(
      "WiFi disconnected!"
    );

    connectWiFi();
  }


  // ==============================================================
  // READ ROLL
  // ==============================================================

  float rawRoll = getRollAngle();


  float rollAngle =
    rawRoll - rollOffset;


  // ==============================================================
  // LIMIT
  // ==============================================================

  if (rollAngle > 90.0) {

    rollAngle = 90.0;
  }


  if (rollAngle < -90.0) {

    rollAngle = -90.0;
  }


  // ==============================================================
  // UDP MESSAGE
  // ==============================================================

  String message =
    String(
      rollAngle,
      2
    );


  udp.beginPacket(
    LAPTOP_IP,
    UDP_PORT
  );


  udp.print(message);


  udp.endPacket();


  // ==============================================================
  // SERIAL DEBUG
  // ==============================================================

  Serial.print("ROLL = ");

  Serial.print(
    rollAngle,
    2
  );

  Serial.println(" deg");


  // ==============================================================
  // 50 Hz
  // ==============================================================

  delay(20);
}