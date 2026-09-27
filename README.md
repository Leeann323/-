# -
这里会有一些python代码，欢迎多多交流

---

# MG996R 舵机远程控制

用电脑或者手机，连上同一个 WiFi，远程控制一个 MG996R 舵机旋转。

项目提供两套可以互换的方案，电脑端的客户端是同一份，两种方案都能用。

第一套方案用 ESP32，一块小板子就够，自带 WiFi 和网页控制界面，推荐第一次做的人选这个。

第二套方案用树莓派或者装了 Linux 的小主机，适合手上已经有这类设备，想用 Python 做更多扩展的人。

## 为什么不能直接把舵机接在电脑上

MG996R 靠五十赫兹的脉冲信号驱动，脉宽在五百到两千五百微秒之间对应不同的角度。

电脑的 USB 口发不出稳定的这种信号，所以必须有一台贴着舵机的小设备来产生脉冲，
电脑只负责通过网络把角度指令发过去。

## 目录结构

```
esp32_servo/esp32_servo.ino   ESP32 固件，第一套方案
pi_host/servo_server.py       服务端，第二套方案，跑在树莓派上
pi_host/requirements.txt      第二套方案的依赖
pc_client/servo_client.py     电脑端客户端，两种方案通用
```

## 接线与供电

不管用哪套方案，接线方式都一样。

舵机的橙色线是信号线，接 ESP32 的十八号引脚，或者树莓派的十七号引脚（BCM 编号）。

舵机的红色线是电源线，接独立的五伏到六伏电源正极。

舵机的棕色线是地线，接独立电源的负极，同时也要接到开发板的地。

这里有两个地方一定要注意。

第一，不要用开发板的五伏引脚直接给 MG996R 供电。MG996R 堵转的时候电流能到二点五安，
会把开发板拉重启，甚至烧掉稳压芯片。要用单独的电源，比如五伏两安以上的适配器或者电池组。

第二，舵机电源和开发板必须共地，也就是负极要连在一起。不共地的话信号会漂，舵机会乱抖或者不动。

## 第一套方案，ESP32

### 一，改配置

打开 esp32_servo/esp32_servo.ino，改这几处。

把 WIFI_SSID 换成你家路由器的名字，把 WIFI_PASSWORD 换成密码。

WIFI_TOKEN 留空表示不校验口令，想加一道口令就填一段文字。

SERVO_PIN 默认是十八号引脚，信号线接的就是它。

其余保持默认即可。没有接舵机也能烧录运行，只是不会有实际动作。

### 二，烧录

用 Arduino IDE 或者命令行的 arduino-cli 都行。

开发板选择 ESP32 Dev Module。

分区方案用默认的就行。去掉蓝牙以后固件大约九百七十七千字节，占默认分区约百分之七十四，
能装得下。如果以后自己加了不少代码，装不下了，再把分区方案改成 Huge APP 即可。

命令行等价写法如下。

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 esp32_servo
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 esp32_servo
```

如果要用更大的分区，在板子名称后面加上分区选项即可，例如
esp32:esp32:esp32:PartitionScheme=huge_app。

### 三，看地址

烧录完成以后打开串口监视器，波特率选一一五二零零，会看到类似下面的内容。

```
WiFi 已连接，设备地址：http://192.168.1.50
也可以访问：http://esp32-servo.local
```

### 四，控制

网页方式，手机和电脑都行。浏览器打开上面打印出来的地址，拖动滑块就能转舵机。

命令行方式，用同一份 Python 客户端。

```bash
python pc_client/servo_client.py --host 192.168.1.50 -a 90
python pc_client/servo_client.py --host 192.168.1.50 --status
```

固件提供的 HTTP 接口一共有三个。

查状态是 /status。

转角度是 /angle 加参数，例如 /angle?v=90 就是转到九十度。

来回扫一遍是 /sweep，从零度到一百八十度再扫回来。

## 第二套方案，树莓派或者 Linux 小主机

### 一，装依赖

```bash
pip install -r pi_host/requirements.txt
```

gpiozero 只有树莓派这类带 GPIO 的设备才装得上。在普通电脑上会装不上，
代码检测到以后会自动切到模拟模式，不会报错。

### 二，改配置

打开 pi_host/servo_server.py，改这几处。

WIFI_BIND_IP 留空，表示同一个 WiFi 下的电脑都能连。

WIFI_PORT 默认是八七六五，电脑端要填一样的数字。

WIFI_TOKEN 留空表示不校验口令。

SERVO_PIN 默认是十七号引脚（BCM 编号），信号线接的就是它。

### 三，启动服务端

```bash
python3 pi_host/servo_server.py             只开 WiFi 服务
python3 pi_host/servo_server.py --simulate  没有接舵机也能跑，只记录角度
```

启动以后终端会打印出可以访问的地址。

### 四，电脑端控制

```bash
python pc_client/servo_client.py --host 树莓派地址 -a 90      转到九十度
python pc_client/servo_client.py --host 树莓派地址 --status   查看状态
python pc_client/servo_client.py --host 树莓派地址 --sweep    来回扫一遍
python pc_client/servo_client.py --host 树莓派地址            进入交互模式
```

如果已经在 pc_client/servo_client.py 顶部把 WIFI_SERVER_IP 填成了树莓派的地址，
上面命令里的 --host 就可以省略。

## 配置项说明

ESP32 固件这边需要关注的是：路由器名字和密码是必改的，WIFI_TOKEN 是访问口令，
SERVO_PIN 是信号线引脚，角度上下限用来保护机械结构，
脉宽范围默认是五百到两千五百微秒，初始角度默认是九十度。

树莓派服务端这边需要关注的是：WIFI_BIND_IP 是监听地址，
WIFI_PORT 是端口，WIFI_TOKEN 是口令，SERVO_PIN 是 BCM 引脚，
角度上下限用来保护机械结构，RELEASE_AFTER_MOVE 为真时舵机到位后断电卸载，
比较省电也不容易发热，但是会松力。

电脑端这边需要关注的是：WIFI_SERVER_IP 和 WIFI_SERVER_PORT 是服务端地址和端口，
WIFI_TOKEN 要和服务端填的一样。

## 安全提示

WIFI_TOKEN 留空的时候，同一个 WiFi 下的任何设备都能控制舵机。
自己家里用问题不大，如果是公共网络，建议填上一段口令。

## 常见问题

连不上，先确认电脑和开发板在同一个 WiFi，再确认地址和端口填对了。
程序会明确提示是连不上还是口令不对。

舵机不动或者一直抖，九成是供电问题。检查是不是用了独立电源，以及有没有共地。

舵机嗡嗡响还发烫，是行程设置超出了机械极限。
把 SERVO_MIN_ANGLE 和 SERVO_MAX_ANGLE 调窄一点。

烧录的时候报 text section exceeds available space in board，
说明固件超过分区容量了，把分区方案改成 Huge APP 即可。

## 许可

Apache License 2.0，见仓库根目录的 LICENSE 文件。
