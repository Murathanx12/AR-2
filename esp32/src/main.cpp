#include <Arduino.h>
#include <HardwareSerial.h>
#include <stdio.h>

// ---------------- Motor pin definitions (ORIGINAL — DO NOT CHANGE) --------
#define DIRA1 3
#define DIRA2 10  // A motor (left front)

#define DIRB1 11
#define DIRB2 12  // B motor (right front)

#define DIRC1 13
#define DIRC2 14  // C motor (left rear)

#define DIRD1 21
#define DIRD2 47  // D motor (right rear)

#define RXD2 16  // GPIO16 as RX
#define TXD2 17  // GPIO17 as TX

// ---------------- IR Sensor pins (5-sensor arc on front semicircle) --------
//         [N]  North (center front)
//        /   \
//     [NW]   [NE]
//     /         \
//   [W]         [E]
//   (left)      (right)
#define IR_W_PIN   5   // bit0 = West (far left)        — Sensor 1, GPIO5
#define IR_NW_PIN  6   // bit1 = Northwest              — Sensor 2, GPIO6
#define IR_N_PIN   7   // bit2 = North (center front)   — Sensor 3, GPIO7
#define IR_NE_PIN  15  // bit3 = Northeast              — Sensor 4, GPIO15
#define IR_E_PIN   45  // bit4 = East (far right)       — Sensor 5, GPIO45

const int irPins[5] = {IR_W_PIN, IR_NW_PIN, IR_N_PIN, IR_NE_PIN, IR_E_PIN};

// ---------------- Ultrasonic sensors (3x HC-SR04) — R4 obstacle detection --
#define TRIG_L_PIN 19   // GPIO19 — left trigger
#define ECHO_L_PIN 20   // GPIO20 — left echo (voltage divider!)
#define TRIG_C_PIN 18   // GPIO18 — center trigger
#define ECHO_C_PIN 1    // GPIO1  — center echo (voltage divider!)
#define TRIG_R_PIN 40   // GPIO40 — right trigger
#define ECHO_R_PIN 39   // GPIO39 — right echo (voltage divider!) ⚠ shared with NeoPixel!

// ---------------- Buzzer — R5 audio indicator ------------------------------
#define BUZZER_PIN 46  // GPIO46

unsigned long buzzerEndTime = 0;

// ---------------- Motor control macros (ORIGINAL — DO NOT CHANGE) ---------
// A = Left front
#define MOTORA_FORWARD(pwm)    do{analogWrite(DIRA1,0);   analogWrite(DIRA2,pwm);}while(0)
#define MOTORA_STOP(pwm)       do{analogWrite(DIRA1,0);   analogWrite(DIRA2,0); }while(0)
#define MOTORA_BACKOFF(pwm)    do{analogWrite(DIRA1,pwm); analogWrite(DIRA2,0); }while(0)

// B = Right front
#define MOTORB_FORWARD(pwm)    do{analogWrite(DIRB1,0);   analogWrite(DIRB2,pwm);}while(0)
#define MOTORB_STOP(pwm)       do{analogWrite(DIRB1,0);   analogWrite(DIRB2,0); }while(0)
#define MOTORB_BACKOFF(pwm)    do{analogWrite(DIRB1,pwm); analogWrite(DIRB2,0); }while(0)

// C = Left rear
#define MOTORC_FORWARD(pwm)    do{analogWrite(DIRC1,pwm); analogWrite(DIRC2,0);}while(0)
#define MOTORC_STOP(pwm)       do{analogWrite(DIRC1,0);   analogWrite(DIRC2,0); }while(0)
#define MOTORC_BACKOFF(pwm)    do{analogWrite(DIRC1,0);   analogWrite(DIRC2,pwm); }while(0)

// D = Right rear
#define MOTORD_FORWARD(pwm)    do{analogWrite(DIRD1,pwm); analogWrite(DIRD2,0);}while(0)
#define MOTORD_STOP(pwm)       do{analogWrite(DIRD1,0);   analogWrite(DIRD2,0); }while(0)
#define MOTORD_BACKOFF(pwm)    do{analogWrite(DIRD1,0);   analogWrite(DIRD2,pwm); }while(0)

#define SERIAL  Serial

// ---------------- PWM parameters (ORIGINAL) ----------------
#define MAX_PWM   200
#define MIN_PWM   50

int Motor_PWM = 160;

HardwareSerial uart2(2); // UART2 for Pi communication

// ---------------- Broadcast intervals ----------------
unsigned long lastIrSend = 0;
const unsigned long IR_SEND_INTERVAL = 50;  // ms (20 Hz)

unsigned long lastDistSend = 0;
const unsigned long DIST_SEND_INTERVAL = 100;  // ms (10 Hz)

// ============================================================
// Low-level motion functions
// ============================================================

void ADVANCE()
{
  MOTORA_FORWARD(Motor_PWM); MOTORB_FORWARD(Motor_PWM);
  MOTORC_FORWARD(Motor_PWM); MOTORD_FORWARD(Motor_PWM);
}

void BACK()
{
  MOTORA_BACKOFF(Motor_PWM); MOTORB_BACKOFF(Motor_PWM);
  MOTORC_BACKOFF(Motor_PWM); MOTORD_BACKOFF(Motor_PWM);
}

void LEFT_2()
{
  MOTORA_BACKOFF(Motor_PWM); MOTORB_FORWARD(Motor_PWM);
  MOTORC_FORWARD(Motor_PWM); MOTORD_BACKOFF(Motor_PWM);
}

void RIGHT_2()
{
  MOTORA_FORWARD(Motor_PWM); MOTORB_BACKOFF(Motor_PWM);
  MOTORC_BACKOFF(Motor_PWM); MOTORD_FORWARD(Motor_PWM);
}

void TURNLEFT()
{
  MOTORA_BACKOFF(Motor_PWM);
  MOTORB_FORWARD(Motor_PWM);
  MOTORC_BACKOFF(Motor_PWM);
  MOTORD_FORWARD(Motor_PWM);
}

void TURNRIGHT()
{
  MOTORA_FORWARD(Motor_PWM);
  MOTORB_BACKOFF(Motor_PWM);
  MOTORC_FORWARD(Motor_PWM);
  MOTORD_BACKOFF(Motor_PWM);
}

void SPINLEFT(int pwm)
{
  MOTORA_BACKOFF(pwm);
  MOTORB_FORWARD(pwm);
  MOTORC_BACKOFF(pwm);
  MOTORD_FORWARD(pwm);
}

void SPINRIGHT(int pwm)
{
  MOTORA_FORWARD(pwm);
  MOTORB_BACKOFF(pwm);
  MOTORC_FORWARD(pwm);
  MOTORD_BACKOFF(pwm);
}

void SIDEPIVOT(int frontPwm, int rearPwm, int direction)
{
  if (direction > 0) {
    MOTORA_FORWARD(frontPwm);
    MOTORB_BACKOFF(frontPwm);
    if (rearPwm > 0) {
      MOTORC_FORWARD(rearPwm);
      MOTORD_BACKOFF(rearPwm);
    } else {
      MOTORC_STOP(0);
      MOTORD_STOP(0);
    }
  } else {
    MOTORA_BACKOFF(frontPwm);
    MOTORB_FORWARD(frontPwm);
    if (rearPwm > 0) {
      MOTORC_BACKOFF(rearPwm);
      MOTORD_FORWARD(rearPwm);
    } else {
      MOTORC_STOP(0);
      MOTORD_STOP(0);
    }
  }
}

void STOP()
{
  MOTORA_STOP(Motor_PWM); MOTORB_STOP(Motor_PWM);
  MOTORC_STOP(Motor_PWM); MOTORD_STOP(Motor_PWM);
}

// Optional moves kept from original
void LEFT_1()
{
  MOTORA_STOP(Motor_PWM);    MOTORB_FORWARD(Motor_PWM);
  MOTORC_FORWARD(Motor_PWM); MOTORD_STOP(Motor_PWM);
}

void LEFT_3()
{
  MOTORA_BACKOFF(Motor_PWM); MOTORB_STOP(Motor_PWM);
  MOTORC_STOP(Motor_PWM);    MOTORD_BACKOFF(Motor_PWM);
}

void RIGHT_1()
{
  MOTORA_FORWARD(Motor_PWM); MOTORB_STOP(Motor_PWM);
  MOTORC_STOP(Motor_PWM);    MOTORD_FORWARD(Motor_PWM);
}

void RIGHT_3()
{
  MOTORA_STOP(Motor_PWM);    MOTORB_BACKOFF(Motor_PWM);
  MOTORC_BACKOFF(Motor_PWM); MOTORD_STOP(Motor_PWM);
}

void TURNLEFT_1()
{
  MOTORA_STOP(Motor_PWM); MOTORB_FORWARD(Motor_PWM);
  MOTORC_STOP(Motor_PWM); MOTORD_FORWARD(Motor_PWM);
}

void TURNRIGHT_1()
{
  MOTORA_FORWARD(Motor_PWM); MOTORB_STOP(Motor_PWM);
  MOTORC_FORWARD(Motor_PWM); MOTORD_STOP(Motor_PWM);
}

// ---------------- Logging ----------------
#define LOG_DEBUG

#ifdef LOG_DEBUG
#define M_LOG SERIAL.print
#else
#define M_LOG
#endif

// ---------------- IO init ----------------
void IO_init()
{
  pinMode(DIRA1, OUTPUT); pinMode(DIRA2, OUTPUT);
  pinMode(DIRB1, OUTPUT); pinMode(DIRB2, OUTPUT);
  pinMode(DIRC1, OUTPUT); pinMode(DIRC2, OUTPUT);
  pinMode(DIRD1, OUTPUT); pinMode(DIRD2, OUTPUT);
  STOP();
}

// ============================================================
// Speed mapping
// ============================================================

int speedToPwm(int speedPercent)
{
  if (speedPercent <= 0) return 0;
  if (speedPercent > 100) speedPercent = 100;
  int pwm = MIN_PWM + (MAX_PWM - MIN_PWM) * speedPercent / 100;
  return pwm;
}

void advance(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { ADVANCE(); }
}

void back(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { BACK(); }
}

void left2(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { LEFT_2(); }
}

void right2(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { RIGHT_2(); }
}

void turnleft(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { TURNLEFT(); }
}

void turnright(int speed)
{
  Motor_PWM = speedToPwm(speed);
  if (Motor_PWM == 0) { STOP(); } else { TURNRIGHT(); }
}

void spinleft(int speed)
{
  int pwm = speedToPwm(speed);
  if (pwm == 0) { STOP(); } else { SPINLEFT(pwm); }
}

void spinright(int speed)
{
  int pwm = speedToPwm(speed);
  if (pwm == 0) { STOP(); } else { SPINRIGHT(pwm); }
}

void sidepivot(int frontSpeed, int rearPercent, int direction)
{
  int fp = speedToPwm(abs(frontSpeed));
  int rp = (rearPercent > 0) ? speedToPwm(abs(frontSpeed) * rearPercent / 100) : 0;
  if (fp == 0) { STOP(); return; }
  SIDEPIVOT(fp, rp, direction);
}

void curve(int leftSpeed, int rightSpeed)
{
  int lp = speedToPwm(abs(leftSpeed));
  int rp = speedToPwm(abs(rightSpeed));

  if (leftSpeed > 0)       { MOTORA_FORWARD(lp); MOTORC_FORWARD(lp); }
  else if (leftSpeed < 0)  { MOTORA_BACKOFF(lp);  MOTORC_BACKOFF(lp);  }
  else                      { MOTORA_STOP(0);      MOTORC_STOP(0);      }

  if (rightSpeed > 0)       { MOTORB_FORWARD(rp); MOTORD_FORWARD(rp); }
  else if (rightSpeed < 0)  { MOTORB_BACKOFF(rp);  MOTORD_BACKOFF(rp);  }
  else                      { MOTORB_STOP(0);      MOTORD_STOP(0);      }
}

// ============================================================
// IR sensor reading
// ============================================================
uint8_t readIrStatus()
{
  uint8_t val = 0;
  for (int i = 0; i < 5; i++) {
    if (digitalRead(irPins[i])) {
      val |= (1 << i);
    }
  }
  return val;
}

// ============================================================
// Ultrasonic sensors (3x HC-SR04) — R4 obstacle detection
// ============================================================
float readUltrasonicSingle(int trigPin, int echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 30000); // 30ms timeout (~5m max)
  if (duration == 0) return -1.0; // timeout = no echo
  return duration * 0.034 / 2.0;  // convert to cm
}

// ============================================================
// Mecanum vector drive (inverse kinematics)
// ============================================================

void driveWheel(char wheel, int speed)
{
  int pwm = speedToPwm(abs(speed));
  switch (wheel) {
    case 'A':
      if (speed > 0) MOTORA_FORWARD(pwm);
      else if (speed < 0) MOTORA_BACKOFF(pwm);
      else MOTORA_STOP(0);
      break;
    case 'B':
      if (speed > 0) MOTORB_FORWARD(pwm);
      else if (speed < 0) MOTORB_BACKOFF(pwm);
      else MOTORB_STOP(0);
      break;
    case 'C':
      if (speed > 0) MOTORC_FORWARD(pwm);
      else if (speed < 0) MOTORC_BACKOFF(pwm);
      else MOTORC_STOP(0);
      break;
    case 'D':
      if (speed > 0) MOTORD_FORWARD(pwm);
      else if (speed < 0) MOTORD_BACKOFF(pwm);
      else MOTORD_STOP(0);
      break;
  }
}

void vectorDrive(int vx, int vy, int omega)
{
  int fl = vx + vy + omega;   // Motor A (left front)
  int fr = vx - vy - omega;   // Motor B (right front)
  int rl = vx - vy + omega;   // Motor C (left rear)
  int rr = vx + vy - omega;   // Motor D (right rear)

  int maxVal = max(max(abs(fl), abs(fr)), max(abs(rl), abs(rr)));
  if (maxVal > 100) {
    fl = fl * 100 / maxVal;
    fr = fr * 100 / maxVal;
    rl = rl * 100 / maxVal;
    rr = rr * 100 / maxVal;
  }

  driveWheel('A', fl);
  driveWheel('B', fr);
  driveWheel('C', rl);
  driveWheel('D', rr);
}

// ============================================================
// UART command handling
// ============================================================

void handleCommand(const String& commandName, const String& paramsStr)
{
  int speed = 0;
  if (paramsStr.length() > 0) {
    speed = paramsStr.toInt();
  }

  SERIAL.print("Command: ");
  SERIAL.print(commandName);
  SERIAL.print("  params: ");
  SERIAL.println(paramsStr);

  if (commandName == "mv_fwd") {
    advance(speed);
  } else if (commandName == "mv_rev") {
    back(speed);
  } else if (commandName == "mv_left") {
    left2(speed);
  } else if (commandName == "mv_right") {
    right2(speed);
  } else if (commandName == "mv_turnleft") {
    turnleft(speed);
  } else if (commandName == "mv_turnright") {
    turnright(speed);
  } else if (commandName == "mv_spinleft") {
    spinleft(speed);
  } else if (commandName == "mv_spinright") {
    spinright(speed);
  } else if (commandName == "mv_sidepivot") {
    int c1 = paramsStr.indexOf(',');
    int c2 = paramsStr.indexOf(',', c1 + 1);
    if (c1 != -1 && c2 != -1) {
      int fs = paramsStr.substring(0, c1).toInt();
      int rp = paramsStr.substring(c1 + 1, c2).toInt();
      int dir = paramsStr.substring(c2 + 1).toInt();
      sidepivot(fs, rp, dir);
    }
  } else if (commandName == "mv_curve") {
    int ci = paramsStr.indexOf(',');
    if (ci != -1) {
      int ls = paramsStr.substring(0, ci).toInt();
      int rs = paramsStr.substring(ci + 1).toInt();
      curve(ls, rs);
    }
  } else if (commandName == "mv_vector") {
    int c1 = paramsStr.indexOf(',');
    int c2 = paramsStr.indexOf(',', c1 + 1);
    if (c1 != -1 && c2 != -1) {
      int vx = paramsStr.substring(0, c1).toInt();
      int vy = paramsStr.substring(c1 + 1, c2).toInt();
      int omega = paramsStr.substring(c2 + 1).toInt();
      vectorDrive(vx, vy, omega);
    }
  } else if (commandName == "stop") {
    STOP();
  }
  // --- R5 Buzzer command ---
  else if (commandName == "buzzer") {
    // Format: buzzer:freq,duration_ms
    int ci = paramsStr.indexOf(',');
    if (ci != -1) {
      int freq = paramsStr.substring(0, ci).toInt();
      int dur = paramsStr.substring(ci + 1).toInt();
      tone(BUZZER_PIN, freq, dur);
      buzzerEndTime = millis() + dur;
    }
  }
  else {
    SERIAL.println("Unknown command");
  }
}

// ============================================================
// Setup & loop
// ============================================================

void setup()
{
  SERIAL.begin(115200);
  uart2.begin(115200, SERIAL_8N1, RXD2, TXD2);
  uart2.setTimeout(10);

  // IR sensor pins (5 sensors on front arc)
  for (int i = 0; i < 5; i++) {
    pinMode(irPins[i], INPUT);
  }

  // Ultrasonic sensors (3x HC-SR04)
  pinMode(TRIG_L_PIN, OUTPUT);
  pinMode(ECHO_L_PIN, INPUT);
  pinMode(TRIG_C_PIN, OUTPUT);
  pinMode(ECHO_C_PIN, INPUT);
  pinMode(TRIG_R_PIN, OUTPUT);
  pinMode(ECHO_R_PIN, INPUT);

  // Buzzer
  pinMode(BUZZER_PIN, OUTPUT);

  SERIAL.println("ESP32 V4 booting...");
  SERIAL.println("UART2 on GPIO16(RX)/GPIO17(TX) at 115200");

  uart2.println("ESP32 Ready (V4 with 3x ultrasonic + buzzer)");
  SERIAL.println("ESP32 Ready — sent hello on UART2");
  IO_init();

  SERIAL.println("Setup complete. Entering main loop.");
}

unsigned long lastPingTime = 0;
const unsigned long PING_INTERVAL_MS = 1500;

void loop()
{
  // --- Read UART commands from Raspberry Pi ---
  if (uart2.available()) {
    String input = uart2.readStringUntil('\n');
    input.trim();

    if (input.length() > 0) {
      SERIAL.print("UART RX: ");
      SERIAL.println(input);

      int separatorIndex = input.indexOf(':');
      if (separatorIndex != -1) {
        String commandName = input.substring(0, separatorIndex);
        String paramsStr   = input.substring(separatorIndex + 1);
        handleCommand(commandName, paramsStr);
      }
    }
  }

  unsigned long now = millis();

  // --- Broadcast IR status to Raspberry Pi at 20 Hz ---
  if (now - lastIrSend >= IR_SEND_INTERVAL) {
    uint8_t ir = readIrStatus();
    uart2.println("IR_STATUS:" + String(ir));
    lastIrSend = now;
  }

  // --- Broadcast 3x ultrasonic distances at 10 Hz ---
  // Read sequentially with brief pauses to avoid echo crosstalk
  if (now - lastDistSend >= DIST_SEND_INTERVAL) {
    float distL = readUltrasonicSingle(TRIG_L_PIN, ECHO_L_PIN);
    delayMicroseconds(500);
    float distC = readUltrasonicSingle(TRIG_C_PIN, ECHO_C_PIN);
    delayMicroseconds(500);
    float distR = readUltrasonicSingle(TRIG_R_PIN, ECHO_R_PIN);

    if (distL >= 0) { uart2.print("DIST_L:"); uart2.println(distL, 1); }
    if (distC >= 0) { uart2.print("DIST_C:"); uart2.println(distC, 1); }
    if (distR >= 0) { uart2.print("DIST_R:"); uart2.println(distR, 1); }
    lastDistSend = now;
  }

  // --- Stop buzzer when duration elapsed ---
  if (buzzerEndTime > 0 && now >= buzzerEndTime) {
    noTone(BUZZER_PIN);
    buzzerEndTime = 0;
  }

  // --- Periodic heartbeat ---
  if (now - lastPingTime >= PING_INTERVAL_MS) {
    uart2.println("Hello from ESP32");
    SERIAL.println("[heartbeat] alive, IR=" + String(readIrStatus()));
    lastPingTime = now;
  }
}
