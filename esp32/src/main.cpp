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

// ---------------- Ultrasonic sensor (1x HC-SR04, center only) -------------
// Build state (2026-04-23): the centre HC-SR04 is wired through a fresh
// bidirectional level shifter. The ESP side sits on the shifter A-channels:
//     TRIG = GPIO8  (formerly SDA)
//     ECHO = GPIO9  (formerly SCL)
// Confirmed working at this pinout via standalone diagnostic — readings
// stable to ~30 cm. The previous GPIO39/40 wiring had a level-shifter fault
// (both A-pins clamped LOW) and is retired.
//
// Pins remain runtime-swappable from the Pi via the UART commands
// `ultra_swap` (flip TRIG/ECHO) and `ultra_pins:t,e` (set explicit pins) so
// the orientation can be flipped without reflashing.
#define TRIG_C_PIN_DEFAULT 8
#define ECHO_C_PIN_DEFAULT 9
int trigPin = TRIG_C_PIN_DEFAULT;
int echoPin = ECHO_C_PIN_DEFAULT;

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
  // --- Ultrasonic pin swap (no-arg) -----------------------------------
  // Swap the current TRIG and ECHO pins. Lets us flip the orientation
  // without reflashing when the physical wires are plugged in backward.
  else if (commandName == "ultra_swap") {
    int tmp = trigPin;
    trigPin = echoPin;
    echoPin = tmp;
    pinMode(trigPin, OUTPUT);
    pinMode(echoPin, INPUT);
    uart2.print("ULTRA: swapped  trig=GPIO");
    uart2.print(trigPin);
    uart2.print("  echo=GPIO");
    uart2.println(echoPin);
  }
  // --- Ultrasonic pin set (explicit) ----------------------------------
  // Format: ultra_pins:trig,echo   (e.g. ultra_pins:39,40)
  else if (commandName == "ultra_pins") {
    int ci = paramsStr.indexOf(',');
    if (ci != -1) {
      int t = paramsStr.substring(0, ci).toInt();
      int e = paramsStr.substring(ci + 1).toInt();
      if (t > 0 && e > 0 && t != e) {
        trigPin = t;
        echoPin = e;
        pinMode(trigPin, OUTPUT);
        pinMode(echoPin, INPUT);
        uart2.print("ULTRA: set  trig=GPIO");
        uart2.print(trigPin);
        uart2.print("  echo=GPIO");
        uart2.println(echoPin);
      }
    }
  }
  // --- Ultrasonic self-test -------------------------------------------
  // Reports the raw level of each pin without triggering. Lets us
  // diagnose:
  //   ECHO = HIGH steady  -> pull-up wins; signal never arrives
  //                          (common-ground fault OR shifter VCCB missing)
  //   ECHO = LOW  steady  -> line pulled to ground somewhere
  //                          (wire shorted / mis-plugged)
  //   ECHO = toggling     -> noise / ungrounded input
  //                          (sensor powered but floating, typical of bad GND)
  // Also pulses TRIG five times spaced 20ms apart so a scope / LED
  // can confirm the trigger side is physically reaching the sensor.
  else if (commandName == "selftest") {
    uart2.print("SELFTEST: trig=GPIO"); uart2.print(trigPin);
    uart2.print("  echo=GPIO"); uart2.println(echoPin);

    // 1. Sample echo for 200ms WITHOUT triggering
    int high_count = 0, low_count = 0;
    unsigned long t_end = millis() + 200;
    while (millis() < t_end) {
      if (digitalRead(echoPin) == HIGH) high_count++;
      else low_count++;
      delayMicroseconds(100);
    }
    uart2.print("SELFTEST: echo idle (no trigger): ");
    uart2.print(high_count); uart2.print(" HIGH, ");
    uart2.print(low_count); uart2.println(" LOW samples over 200ms");

    // 2. Five trigger pulses with 20ms spacing, report echo each time
    for (int i = 0; i < 5; i++) {
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      long dur = pulseIn(echoPin, HIGH, 30000);
      uart2.print("SELFTEST: pulse "); uart2.print(i+1);
      uart2.print(" -> duration="); uart2.print(dur); uart2.println(" us");
      delay(20);
    }
    uart2.println("SELFTEST: done");
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

  // Ultrasonic sensor — CENTER ONLY on this build
  // (Left + Right are wired in firmware but the physical pins are
  // unconnected; reads on those pins are skipped to save the 60 ms of
  // pulseIn timeout per cycle that two missing sensors would cost.)
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  // Buzzer
  pinMode(BUZZER_PIN, OUTPUT);

  SERIAL.println("ESP32 V4.5 booting...");
  SERIAL.println("UART2 on GPIO16(RX)/GPIO17(TX) at 115200");
  SERIAL.print("Ultrasonic: TRIG=GPIO");
  SERIAL.print(trigPin);
  SERIAL.print(" ECHO=GPIO");
  SERIAL.println(echoPin);

  uart2.print("ESP32 Ready (V4.5 — ultrasonic TRIG=");
  uart2.print(trigPin);
  uart2.print(" ECHO=");
  uart2.print(echoPin);
  uart2.println(", `ultra_swap` to flip)");
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

  // --- Broadcast CENTER ultrasonic distance at 10 Hz ---
  // Center sensor is the only HC-SR04 wired in this build. Always
  // print the value (even on timeout = -1.0) so the Pi can see the
  // sensor is being read; -1.0 means "no echo within 30 ms".
  if (now - lastDistSend >= DIST_SEND_INTERVAL) {
    float distC = readUltrasonicSingle(trigPin, echoPin);
    uart2.print("DIST_C:"); uart2.println(distC, 1);
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
