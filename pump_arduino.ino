#include <AccelStepper.h>
#include <string.h>

// STEP = 10, DIR = 9
AccelStepper stepper(AccelStepper::DRIVER, 10, 9);

const int LIMIT_FRONT = A0;


const bool LIMIT_TRIGGERED_IS_HIGH = true;

const int PUSH_SIGN = -1;

char serialBuffer[32];
int serialIndex = 0;

bool wasMoving = false;
bool isPaused = false;

long pausedTarget = 0;
long currentMoveSpeed = 1000;

bool limitHit() {
  int v = digitalRead(LIMIT_FRONT);
  return LIMIT_TRIGGERED_IS_HIGH ? (v == HIGH) : (v == LOW);
}

bool movingTowardLimit() {
  long dist = stepper.distanceToGo();

  if (PUSH_SIGN > 0) {
    return dist > 0;
  } else {
    return dist < 0;
  }
}

bool targetTowardLimit(long target) {
  long delta = target - stepper.currentPosition();

  if (PUSH_SIGN > 0) {
    return delta > 0;
  } else {
    return delta < 0;
  }
}

bool fiveDigits(const char *s) {
  for (int i = 0; i < 5; i++) {
    if (s[i] < '0' || s[i] > '9') return false;
  }
  return true;
}

long parseFiveDigits(const char *s) {
  long value = 0;
  for (int i = 0; i < 5; i++) {
    value = value * 10 + (s[i] - '0');
  }
  return value;
}

void forceStopNow() {
  stepper.moveTo(stepper.currentPosition());
}

void pauseMotion() {
  if (isPaused) {
    Serial.println("PAUSED");
    return;
  }

  if (stepper.distanceToGo() == 0) {
    Serial.println("ERR_NOT_MOVING");
    return;
  }

  pausedTarget = stepper.targetPosition();
  forceStopNow();

  isPaused = true;
  wasMoving = false;

  Serial.println("PAUSED");
  Serial.print("POS=");
  Serial.println(stepper.currentPosition());
}

void resumeMotion() {
  if (!isPaused) {
    Serial.println("ERR_NOT_PAUSED");
    return;
  }

  if (limitHit() && targetTowardLimit(pausedTarget)) {
    Serial.println("ERR_LIMIT");
    Serial.print("POS=");
    Serial.println(stepper.currentPosition());
    return;
  }

  stepper.setMaxSpeed(currentMoveSpeed);
  stepper.moveTo(pausedTarget);

  isPaused = false;
  wasMoving = true;

  Serial.println("RESUMED");
  Serial.print("TARGET=");
  Serial.println(pausedTarget);
}

void stopMotion() {
  forceStopNow();

  isPaused = false;
  wasMoving = false;

  Serial.println("STOPPED");
  Serial.print("POS=");
  Serial.println(stepper.currentPosition());
}

void printLimitStatus() {
  Serial.print("LIMIT_RAW=");
  Serial.print(digitalRead(LIMIT_FRONT));
  Serial.print(" LIMIT_HIT=");
  Serial.println(limitHit() ? 1 : 0);
}

void handleMoveCommand(char *cmd) {
  // Format: d00000v00000v00000d1
  if (strlen(cmd) != 20) {
    Serial.println("ERR_FORMAT");
    return;
  }

  if (cmd[0] != 'd' || cmd[6] != 'v' || cmd[12] != 'v' || cmd[18] != 'd') {
    Serial.println("ERR_FORMAT");
    return;
  }

  if (!fiveDigits(cmd + 1) || !fiveDigits(cmd + 13)) {
    Serial.println("ERR_NUMBER");
    return;
  }

  int direction = cmd[19] - '0';

  if (direction != 0 && direction != 1) {
    Serial.println("ERR_DIRECTION");
    return;
  }

  if (stepper.distanceToGo() != 0 || isPaused) {
    Serial.println("ERR_BUSY");
    return;
  }

  long moveSteps = parseFiveDigits(cmd + 1);
  long speedSteps = parseFiveDigits(cmd + 13);

  if (moveSteps <= 0 || speedSteps <= 0) {
    Serial.println("ERR_ZERO");
    return;
  }

  // d1 = 推
  // d0 = 退
  if (direction == 1) {
    moveSteps = moveSteps * PUSH_SIGN;
  } else {
    moveSteps = moveSteps * -PUSH_SIGN;
  }

  if (limitHit() && direction == 1) {
    Serial.println("ERR_LIMIT");
    Serial.print("POS=");
    Serial.println(stepper.currentPosition());
    return;
  }

  long target = stepper.currentPosition() + moveSteps;

  currentMoveSpeed = speedSteps;

  stepper.setMaxSpeed(speedSteps);
  stepper.moveTo(target);

  wasMoving = true;

  Serial.print("START dir=d");
  Serial.print(direction);
  Serial.print(" steps=");
  Serial.print(moveSteps);
  Serial.print(" speed=");
  Serial.print(speedSteps);
  Serial.print(" target=");
  Serial.println(target);
}

void handleCommand(char *cmd) {
  if (strcmp(cmd, "P") == 0) {
    pauseMotion();
    return;
  }

  if (strcmp(cmd, "R") == 0) {
    resumeMotion();
    return;
  }

  if (strcmp(cmd, "S") == 0) {
    stopMotion();
    return;
  }

  if (strcmp(cmd, "L") == 0) {
    printLimitStatus();
    return;
  }

  handleMoveCommand(cmd);
}

void readSerialCommand() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\r' || c == '\n') {
      if (serialIndex > 0) {
        serialBuffer[serialIndex] = '\0';
        handleCommand(serialBuffer);
        serialIndex = 0;
      }
    } else {
      if (serialIndex < 31) {
        serialBuffer[serialIndex++] = c;
      } else {
        serialIndex = 0;
        Serial.println("ERR_OVERFLOW");
      }
    }
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(LIMIT_FRONT, INPUT_PULLUP);

  stepper.setMaxSpeed(1000.0);
  stepper.setAcceleration(500.0);
  stepper.setCurrentPosition(0);

  Serial.println("READY V4");
  Serial.print("PUSH_SIGN=");
  Serial.println(PUSH_SIGN);
  Serial.print("POS=");
  Serial.println(stepper.currentPosition());
  printLimitStatus();
}

void loop() {
  readSerialCommand();

  if (!isPaused && limitHit() && movingTowardLimit()) {
    forceStopNow();

    wasMoving = false;

    Serial.println("ERR_LIMIT");
    Serial.print("POS=");
    Serial.println(stepper.currentPosition());
  }

  stepper.run();

  if (wasMoving && stepper.distanceToGo() == 0) {
    wasMoving = false;

    Serial.println("DONE");
    Serial.print("POS=");
    Serial.println(stepper.currentPosition());
  }
}