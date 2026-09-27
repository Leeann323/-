#!/usr/bin/env python3
"""
MG996R 舵机远程控制电脑端

这个文件在电脑上运行，把角度通过网络发给服务端。
两种方案都能用同一个客户端，也就是 ESP32 固件和树莓派服务端都支持。

用法示例
    python servo_client.py                 进入交互模式，输入角度回车
    python servo_client.py -a 90           直接转到九十度
    python servo_client.py --status        查看当前状态
    python servo_client.py --sweep         从零度到一百八十度来回扫一遍
    python servo_client.py --host 192.168.1.50 --port 8765 -a 90

下面标着「可填」的地方需要和服务端保持一致。不填也能运行，
只是连不上服务端的时候会给出清楚的提示。
"""

import argparse
import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# 可填一，服务端地址
# WIFI_SERVER_IP 填舵机那台设备的局域网地址。不知道的话，
# 先看服务端启动时打印出来的地址。
# WIFI_TOKEN 和服务端填一样的，服务端没填就留空。
WIFI_SERVER_IP = "192.168.1.100"
WIFI_SERVER_PORT = 8765
WIFI_TOKEN = ""

# 请求超时时间，单位是秒
REQUEST_TIMEOUT = 5.0


class ServoLink:
    """负责和服务端通信，对外只提供转角度和查状态两个方法。"""

    def __init__(self, host, port, token):
        self.host = host
        self.port = port
        self.token = token

    def request(self, path, params=None):
        """发一次请求，返回服务端解析好的结果。出错时返回一个说明。"""
        query = dict(params or {})
        if self.token:
            query["token"] = self.token

        url = "http://%s:%d%s" % (self.host, self.port, path)
        if query:
            url += "?" + urlencode(query)

        request = Request(url, headers={"Accept": "application/json"})

        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 服务端返回了错误状态码，但内容还是 JSON，照样解析出来
            body = exc.read().decode("utf-8", "ignore")
            try:
                return json.loads(body)
            except Exception:
                return {"ok": False, "error": "服务端返回 HTTP %d" % exc.code}
        except URLError as exc:
            return {"ok": False, "error": "连不上 %s:%d，原因 %s" % (self.host, self.port, exc.reason)}
        except socket.timeout:
            return {"ok": False, "error": "请求超时"}
        except (ConnectionError, OSError) as exc:
            # 服务端中途断开之类的网络问题，也给出清楚提示而不是直接抛出异常
            return {"ok": False, "error": "连接中断，原因 %s" % exc}

    def angle(self, value):
        return self.request("/angle", {"v": value})

    def status(self):
        return self.request("/status")


def show(reply, label=""):
    """把服务端返回的结果打印成人看得懂的一行话。"""
    prefix = ("%s " % label) if label else ""

    if reply.get("ok"):
        if "data" in reply:
            data = reply["data"]
            print("%s正常，当前角度 %.1f 度，后端是 %s" % (
                prefix, data.get("angle", 0), data.get("backend", "未知")))
        elif "angle" in reply:
            print("%s已转到 %.1f 度" % (prefix, reply["angle"]))
        else:
            print("%s%s" % (prefix, reply.get("msg", "成功")))
    else:
        print("%s失败，%s" % (prefix, reply.get("error", "未知错误")))

    return bool(reply.get("ok"))


def do_sweep(link):
    """从零度扫到一百八十度再扫回来。"""
    angles = list(range(0, 181, 15)) + list(range(165, -1, -15))
    for angle in angles:
        show(link.angle(angle))
        time.sleep(0.25)


def interactive(link):
    """交互模式，一直输入角度直到退出。"""
    print("输入角度数字，范围零到一百八十，回车即可旋转。")
    print("输入 s 查看状态，输入 q 退出。")

    while True:
        try:
            text = input("角度> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if text in ("q", "quit", "exit"):
            break
        if text in ("s", "status"):
            show(link.status())
            continue
        if not text:
            continue

        try:
            angle = float(text)
        except ValueError:
            print("请输入一个数字，比如 90")
            continue

        if angle < 0 or angle > 180:
            print("角度请控制在 0 到 180 之间")
            continue

        show(link.angle(angle))


def main():
    parser = argparse.ArgumentParser(description="MG996R 舵机远程控制电脑端")
    parser.add_argument("--host", default=WIFI_SERVER_IP, help="服务端地址")
    parser.add_argument("--port", type=int, default=WIFI_SERVER_PORT, help="服务端端口")
    parser.add_argument("--token", default=WIFI_TOKEN, help="访问口令")
    parser.add_argument("-a", "--angle", type=float, default=None,
                        help="只转一个角度然后退出")
    parser.add_argument("--sweep", action="store_true", help="从零度到一百八十度来回扫一遍")
    parser.add_argument("--status", action="store_true", help="只查一次状态")
    args = parser.parse_args()

    if args.angle is not None and not (0 <= args.angle <= 180):
        print("角度请控制在 0 到 180 之间")
        return 1

    link = ServoLink(args.host, args.port, args.token)

    if args.status:
        return 0 if show(link.status()) else 1

    if args.angle is not None:
        return 0 if show(link.angle(args.angle)) else 1

    if args.sweep:
        do_sweep(link)
        return 0

    if sys.stdin.isatty():
        interactive(link)
        return 0

    print("当前不是交互环境，请用 -a 指定角度，或者用 --sweep 和 --status。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
