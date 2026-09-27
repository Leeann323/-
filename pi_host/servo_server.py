#!/usr/bin/env python3
"""
MG996R 舵机远程控制服务端

这个文件跑在和舵机连在一起的那台设备上，比如树莓派或者装了 Linux 的小主机。
电脑端请配合 pc_client 文件夹里的 servo_client.py 一起使用。

用法示例
    python3 servo_server.py            只开 WiFi 服务，最常用
    python3 servo_server.py --simulate 没有接舵机也能跑，只记录角度

下面标着「可填」的地方都是需要你自己改的。不改也能直接运行，
只是访问地址和引脚会用默认值。
"""

import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 可填一，WiFi 设置
# WIFI_BIND_IP 留空表示监听所有网卡，同一个 WiFi 下的电脑都能连。
# WIFI_PORT 是服务端口，电脑端要填一样的数字。
# WIFI_TOKEN 留空表示不校验口令，填上一段文字则要求访问时带上同样的值。
WIFI_BIND_IP = ""
WIFI_PORT = 8765
WIFI_TOKEN = ""

# 可填二，舵机接线与行程
# SERVO_PIN 是舵机信号线接的引脚，这里用的是树莓派的 BCM 编号。
# SERVO_MIN_ANGLE 和 SERVO_MAX_ANGLE 是允许转到的角度范围，用来保护机械结构。
# SERVO_MIN_PULSE_US 和 SERVO_MAX_PULSE_US 是脉宽的微秒数，MG996R 通常用五百到两千五百。
# SERVO_START_ANGLE 是开机时的初始角度。
# RELEASE_AFTER_MOVE 为真时，舵机到位以后断电卸载，比较省电也不容易发热，但是会松力。
SERVO_PIN = 17
SERVO_MIN_ANGLE = 0
SERVO_MAX_ANGLE = 180
SERVO_MIN_PULSE_US = 500
SERVO_MAX_PULSE_US = 2500
SERVO_START_ANGLE = 90
RELEASE_AFTER_MOVE = False
MOVE_SETTLE_SECONDS = 0.8

# 可填三，是否打印每一条 HTTP 日志。排查问题的时候可以改成 True。
VERBOSE = False


def clamp(value, low, high):
    """把数值限制在上下限之间。"""
    if value < low:
        return low
    if value > high:
        return high
    return value


class ServoController:
    """把角度真正写到舵机上。如果这台设备没有 GPIO 硬件，会自动降级成模拟模式。"""

    def __init__(self, force_simulate=False):
        self._lock = threading.Lock()
        self._angle = float(SERVO_START_ANGLE)
        self._servo = None
        self._simulate = True
        self._backend = "模拟模式，只记录角度，没有真实输出"

        if not force_simulate:
            try:
                # gpiozero 只有树莓派这类带 GPIO 的设备才装得上
                from gpiozero import Servo

                self._servo = Servo(
                    SERVO_PIN,
                    min_pulse_width=SERVO_MIN_PULSE_US / 1000000.0,
                    max_pulse_width=SERVO_MAX_PULSE_US / 1000000.0,
                )
                self._simulate = False
                self._backend = "gpiozero，真实舵机"
            except Exception as exc:
                self._backend = "模拟模式，加载 gpiozero 失败，原因 %s" % exc

        self.set_angle(SERVO_START_ANGLE)

    def set_angle(self, angle):
        """转到指定角度，超出范围会自动夹到边界。"""
        angle = clamp(float(angle), SERVO_MIN_ANGLE, SERVO_MAX_ANGLE)

        with self._lock:
            self._angle = angle
            if self._servo is not None:
                # gpiozero 的取值区间是负一到正一，分别对应最小脉宽和最大脉宽
                self._servo.value = (angle - 90.0) / 90.0

        if RELEASE_AFTER_MOVE and self._servo is not None:
            time.sleep(MOVE_SETTLE_SECONDS)
            with self._lock:
                self._servo.detach()

        print("[舵机] 转到 %.1f 度" % angle)
        return angle

    def status(self):
        """返回当前状态，供接口查询。"""
        with self._lock:
            angle = self._angle
        return {
            "angle": angle,
            "backend": self._backend,
            "simulate": self._simulate,
            "pin": SERVO_PIN,
            "range": [SERVO_MIN_ANGLE, SERVO_MAX_ANGLE],
        }


def local_ipv4_list():
    """猜一下本机的局域网地址，只是为了让启动提示更友好。"""
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        found.append(probe.getsockname()[0])
        probe.close()
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except Exception:
        pass

    if not found:
        return ["127.0.0.1"]
    return found


def build_handler(controller, token):
    """构造一个很轻的 HTTP 接口，提供转角度和查状态两个功能。"""

    class ServoHandler(BaseHTTPRequestHandler):
        server_version = "MG996RServo/1.0"

        def log_message(self, fmt, *args):
            if VERBOSE:
                print("[HTTP] " + (fmt % args))

        def reply(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self, query):
            # 设置了口令就要求带对，没设置就直接放行
            if token:
                given = query.get("token", [""])[0] or self.headers.get("X-Token", "")
                if given != token:
                    return self.reply(401, {"ok": False, "error": "口令不对"})

            path = urlparse(self.path).path

            if path in ("/", "/help"):
                return self.reply(200, {
                    "ok": True,
                    "usage": {
                        "转角度": "/angle?v=90",
                        "查状态": "/status",
                    },
                })

            if path == "/status":
                return self.reply(200, {"ok": True, "data": controller.status()})

            if path == "/angle":
                raw = query.get("v", query.get("angle", [None]))[0]
                if raw is None:
                    return self.reply(400, {"ok": False, "error": "缺少参数 v"})
                try:
                    value = float(raw)
                except ValueError:
                    return self.reply(400, {"ok": False, "error": "角度必须是数字"})
                moved = controller.set_angle(value)
                return self.reply(200, {"ok": True, "angle": moved})

            return self.reply(404, {"ok": False, "error": "没有这个接口"})

        def do_GET(self):
            self.dispatch(parse_qs(urlparse(self.path).query))

        def do_POST(self):
            # 也支持直接发一段 JSON，内容是角度
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0

            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {}

            query = parse_qs(urlparse(self.path).query)
            if isinstance(payload, dict) and "v" in payload:
                query.setdefault("v", [str(payload["v"])])
            self.dispatch(query)

    return ServoHandler


def start_wifi_server(controller):
    """启动 WiFi 服务，一直运行到按 Ctrl 加 C 退出。"""
    handler = build_handler(controller, WIFI_TOKEN)

    try:
        httpd = ThreadingHTTPServer((WIFI_BIND_IP, WIFI_PORT), handler)
    except OSError as exc:
        print("[WiFi] 端口 %d 起不来，原因 %s" % (WIFI_PORT, exc))
        return

    httpd.daemon_threads = True

    print("[WiFi] 已启动，监听端口 %d" % WIFI_PORT)
    print("[WiFi] 同一个 WiFi 下的电脑可以访问下面的地址")
    for ip in local_ipv4_list():
        print("       http://%s:%d/status" % (ip, WIFI_PORT))
    if WIFI_TOKEN:
        print("[WiFi] 已开启口令校验，电脑端要填同样的 WIFI_TOKEN")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="MG996R 舵机远程控制服务端")
    parser.add_argument("--simulate", action="store_true",
                        help="强制模拟模式，不需要接舵机也能跑")
    parser.add_argument("--angle", type=float, default=None,
                        help="启动后先转到某个角度")
    parser.add_argument("--verbose", action="store_true",
                        help="打印每一条 HTTP 日志")
    args = parser.parse_args()

    globals()["VERBOSE"] = args.verbose

    controller = ServoController(force_simulate=args.simulate)
    print("[启动] 舵机后端是 %s" % controller.status()["backend"])

    if args.angle is not None:
        controller.set_angle(args.angle)

    print("[启动] 就绪，按 Ctrl 加 C 退出。")
    try:
        start_wifi_server(controller)
    except KeyboardInterrupt:
        print()
        print("[启动] 收到退出信号，已停止。")


if __name__ == "__main__":
    main()
