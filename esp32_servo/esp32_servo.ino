/*
 * MG996R 舵机远程控制 ESP32 固件
 *
 * 把 ESP32 贴在舵机旁边，它自带 WiFi 和硬件 PWM，可以直接输出舵机需要的
 * 50 赫兹信号。电脑或者手机连上同一个 WiFi 以后，用浏览器或者 Python 客户端
 * 就能远程转动舵机。
 *
 * 提供两种控制方式。
 * 第一种是网页，浏览器打开设备地址，拖动滑块即可。
 * 第二种是 HTTP 接口，也就是 /angle 和 /status，方便程序调用。
 *
 * 下面标着「可填」的地方都是需要你自己改的。没有接舵机也能烧录运行，
 * 只是不会有实际动作。
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// 可填一，WiFi 设置
// WIFI_SSID 填你家路由器的名字，WIFI_PASSWORD 填密码。
// HOST_NAME 是设备在局域网里的名字，可以用来访问 http://名字.local。
// WIFI_TOKEN 留空表示不校验口令，填上一段文字则要求访问时带上同样的值。
const char* WIFI_SSID     = "你的WiFi名字";
const char* WIFI_PASSWORD = "你的WiFi密码";
const char* HOST_NAME     = "esp32-servo";
const char* WIFI_TOKEN    = "";

// 可填二，舵机接线与行程
// SERVO_PIN 是舵机信号线接的引脚，默认十八号。
// SERVO_MIN_ANGLE 和 SERVO_MAX_ANGLE 是允许转到的角度范围，用来保护机械结构。
// SERVO_MIN_PULSE_US 和 SERVO_MAX_PULSE_US 是脉宽的微秒数，MG996R 通常用五百到两千五百。
// SERVO_START_ANGLE 是开机时的初始角度。
const int SERVO_PIN           = 18;
const float SERVO_MIN_ANGLE   = 0;
const float SERVO_MAX_ANGLE   = 180;
const int SERVO_MIN_PULSE_US  = 500;
const int SERVO_MAX_PULSE_US  = 2500;
const float SERVO_START_ANGLE = 90;

// 可填三，PWM 参数，一般不用动
const int PWM_FREQ_HZ  = 50;
const int PWM_RES_BITS = 16;
const int PWM_CHANNEL  = 0;

// MG996R 的脉宽周期固定是二十毫秒，也就是五十赫兹
const float PWM_PERIOD_US = 1000000.0 / PWM_FREQ_HZ;

WebServer server(80);

float currentAngle = SERVO_START_ANGLE;

// 把角度真正写到舵机上，超出范围会自动夹到边界
void writeServo(float angle) {
  if (angle < SERVO_MIN_ANGLE) angle = SERVO_MIN_ANGLE;
  if (angle > SERVO_MAX_ANGLE) angle = SERVO_MAX_ANGLE;
  currentAngle = angle;

  float ratio = (angle - SERVO_MIN_ANGLE) / (SERVO_MAX_ANGLE - SERVO_MIN_ANGLE);
  float pulseUs = SERVO_MIN_PULSE_US + ratio * (SERVO_MAX_PULSE_US - SERVO_MIN_PULSE_US);
  uint32_t maxDuty = (1u << PWM_RES_BITS) - 1u;
  uint32_t duty = (uint32_t)(pulseUs / PWM_PERIOD_US * maxDuty);

  // 不同版本的 ESP32 开发包函数名不一样，这里做了兼容
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(SERVO_PIN, duty);
#else
  ledcWrite(PWM_CHANNEL, duty);
#endif
}

void setupPwm() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(SERVO_PIN, PWM_FREQ_HZ, PWM_RES_BITS);
#else
  ledcSetup(PWM_CHANNEL, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcAttachPin(SERVO_PIN, PWM_CHANNEL);
#endif
  writeServo(SERVO_START_ANGLE);
}

String statusJson() {
  String json = "{\"ok\":true,\"data\":{";
  json += "\"angle\":" + String(currentAngle, 1);
  json += ",\"pin\":" + String(SERVO_PIN);
  json += ",\"range\":[" + String(SERVO_MIN_ANGLE, 0) + "," + String(SERVO_MAX_ANGLE, 0) + "]";
  json += ",\"backend\":\"ESP32 LEDC\"}}";
  return json;
}

// 检查访问口令，没有设置口令就直接放行
bool tokenOk() {
  if (strlen(WIFI_TOKEN) == 0) return true;
  if (server.hasArg("token") && server.arg("token") == WIFI_TOKEN) return true;
  if (server.hasHeader("X-Token") && server.header("X-Token") == WIFI_TOKEN) return true;
  return false;
}

// 网页控制界面的内容
const char INDEX_HTML[] PROGMEM = R"HTML(<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 舵机控制</title>
<style>
body{font-family:sans-serif;max-width:520px;margin:24px auto;padding:0 16px;color:#222}
h1{font-size:20px}
#angle{font-size:34px;text-align:center;margin:8px 0}
input[type=range]{width:100%;height:36px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{flex:1;min-width:64px;padding:10px 0;font-size:15px;cursor:pointer}
#msg{margin-top:14px;color:#666;font-size:14px;min-height:20px}
</style>
</head>
<body>
<h1>ESP32 舵机控制</h1>
<div id="angle">90 度</div>
<input id="slider" type="range" min="0" max="180" value="90" step="1">
<div class="row">
<button onclick="go(0)">0 度</button>
<button onclick="go(45)">45 度</button>
<button onclick="go(90)">90 度</button>
<button onclick="go(135)">135 度</button>
<button onclick="go(180)">180 度</button>
</div>
<div class="row">
<button onclick="sweep()">来回扫一遍</button>
<button onclick="refresh()">刷新状态</button>
</div>
<div id="msg">拖动滑块即可转动舵机。</div>
<script>
var token = "%%TOKEN%%";
var slider = document.getElementById("slider");
var angleLabel = document.getElementById("angle");
var msg = document.getElementById("msg");
var timer = null;

function url(path){ return token ? path + "?token=" + encodeURIComponent(token) : path; }

function go(v){
  angleLabel.textContent = v + " 度";
  fetch(url("/angle?v=" + v)).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ msg.textContent = "已转到 " + d.angle + " 度"; }
    else { msg.textContent = "失败：" + (d.error || "未知错误"); }
  }).catch(function(){ msg.textContent = "连不上设备"; });
}

slider.addEventListener("input", function(){
  angleLabel.textContent = slider.value + " 度";
  clearTimeout(timer);
  var v = slider.value;
  timer = setTimeout(function(){ go(v); }, 150);
});

function refresh(){
  fetch(url("/status")).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ slider.value = d.data.angle; angleLabel.textContent = d.data.angle + " 度";
      msg.textContent = "当前角度 " + d.data.angle + " 度"; }
  }).catch(function(){ msg.textContent = "连不上设备"; });
}

function sweep(){
  var seq = [0,30,60,90,120,150,180,150,120,90,60,30,0], i = 0;
  msg.textContent = "正在扫动……";
  var t = setInterval(function(){
    if(i >= seq.length){ clearInterval(t); msg.textContent = "扫动结束"; return; }
    slider.value = seq[i]; angleLabel.textContent = seq[i] + " 度"; go(seq[i]); i++;
  }, 350);
}
refresh();
</script>
</body>
</html>)HTML";

void handleIndex() {
  String page = String(INDEX_HTML);
  page.replace("%%TOKEN%%", String(WIFI_TOKEN));
  server.send(200, "text/html; charset=utf-8", page);
}

void handleStatus() {
  if (!tokenOk()) {
    server.send(401, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"口令不对\"}");
    return;
  }
  server.send(200, "application/json; charset=utf-8", statusJson());
}

void handleAngle() {
  if (!tokenOk()) {
    server.send(401, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"口令不对\"}");
    return;
  }

  String raw = server.hasArg("v") ? server.arg("v") : (server.hasArg("angle") ? server.arg("angle") : "");
  if (raw.length() == 0) {
    server.send(400, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"缺少参数 v\"}");
    return;
  }

  // 只允许数字和正负号小数点，防止收到乱七八糟的内容
  for (unsigned int i = 0; i < raw.length(); i++) {
    char c = raw[i];
    if (!(isDigit(c) || c == '.' || c == '-' || c == '+')) {
      server.send(400, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"角度必须是数字\"}");
      return;
    }
  }

  writeServo(raw.toFloat());
  String json = "{\"ok\":true,\"angle\":" + String(currentAngle, 1) + "}";
  server.send(200, "application/json; charset=utf-8", json);
}

void handleSweep() {
  if (!tokenOk()) {
    server.send(401, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"口令不对\"}");
    return;
  }

  float seq[] = {0, 30, 60, 90, 120, 150, 180, 150, 120, 90, 60, 30, 0};
  for (unsigned int i = 0; i < sizeof(seq) / sizeof(seq[0]); i++) {
    writeServo(seq[i]);
    delay(350);
  }
  server.send(200, "application/json; charset=utf-8", statusJson());
}

void handleNotFound() {
  server.send(404, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"没有这个接口\"}");
}

// 连接 WiFi，最多等十五秒
void setupWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOST_NAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("正在连接 WiFi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi 已连接，设备地址：http://");
    Serial.println(WiFi.localIP());
    if (MDNS.begin(HOST_NAME)) {
      Serial.print("也可以访问：http://");
      Serial.print(HOST_NAME);
      Serial.println(".local");
    }
  } else {
    Serial.println("WiFi 没连上，网页和接口暂时不可用。");
    Serial.println("请检查可填一里面的路由器名字和密码。");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("MG996R 舵机远程控制 ESP32 固件启动");

  setupPwm();
  Serial.print("舵机初始角度：");
  Serial.println(SERVO_START_ANGLE);

  setupWifi();

  server.on("/", handleIndex);
  server.on("/status", handleStatus);
  server.on("/angle", handleAngle);
  server.on("/sweep", handleSweep);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println("HTTP 服务已启动，接口是 /angle 和 /status");

  Serial.println("就绪。");
}

void loop() {
  server.handleClient();
  delay(2);
}
