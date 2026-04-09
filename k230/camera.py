import time, os, struct, network, socket

from media.sensor import *
from media.display import *
from media.media import *

# ── WiFi 配置 ────────────────────────────────────────────────
SSID     = "@TAKS"       # WiFi 名称
PASSWORD = "88888888"    # WiFi 密码

PC_IP   = "255.255.255.255"  # UDP 广播地址
PC_PORT = 5566               # UDP 端口

WIFI_CONNECT_TIMEOUT = 30
WIFI_ACTIVE_WAIT     = 3
WIFI_IP_WAIT         = 5

# ── 分辨率 ───────────────────────────────────────────────────
FRAME_W = 640
FRAME_H = 480

sensor_id = 0
sensor    = None


def connect_wifi():
    """连接 WiFi，返回本机 IP"""
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
        time.sleep(WIFI_ACTIVE_WAIT)
    if not sta.isconnected():
        print(f"正在连接 WiFi: {SSID} ...")
        sta.connect(SSID, PASSWORD)
        for i in range(WIFI_CONNECT_TIMEOUT):
            if sta.isconnected():
                break
            time.sleep(1)
            print(f"  等待连接... {i+1}/{WIFI_CONNECT_TIMEOUT}s")
    if sta.isconnected():
        for _ in range(WIFI_IP_WAIT):
            ip = sta.ifconfig()[0]
            if ip != "0.0.0.0":
                break
            time.sleep(1)
        ip = sta.ifconfig()[0]
        if ip == "0.0.0.0":
            raise RuntimeError("WiFi 已关联但未获得 IP（DHCP 超时）")
        print(f"WiFi 已连接，本机 IP: {ip}")
        return ip
    else:
        raise RuntimeError("WiFi 连接失败")


FRAG_SIZE = 1400  # 每个 UDP 分片的 JPEG 载荷字节数（小于 MTU 1500）
JPEG_QUALITY = 40  # JPEG 压缩质量


def send_frame(sock, jpeg_bytes, w, h):
    """UDP 广播发送一帧，自动分片
    帧头包（frag_id=0xFFFF）: [0xFF 0xFF][LEN:4][W:2][H:2]  共 10 字节
    数据分片包:               [frag_id:2][frag_total:2][data]
    """
    dest = (PC_IP, PC_PORT)
    n = len(jpeg_bytes)
    # 发送帧头包，通知 PC 本帧总长度和尺寸
    header_pkt = struct.pack('>HHIHH', 0xFFFF, 0, n, w, h)
    sock.sendto(header_pkt, dest)
    # 分片发送 JPEG 数据
    total = (n + FRAG_SIZE - 1) // FRAG_SIZE
    for i in range(total):
        chunk = jpeg_bytes[i * FRAG_SIZE: (i + 1) * FRAG_SIZE]
        pkt = struct.pack('>HH', i, total) + chunk
        sock.sendto(pkt, dest)


connect_wifi()

# ── UDP 广播 socket ──────────────────────────────────────────
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
print(f"UDP 广播 -> {PC_IP}:{PC_PORT}")

try:
    sensor = Sensor(id=sensor_id)
    sensor.reset()
    sensor.set_framesize(Sensor.VGA, chn=CAM_CHN_ID_0)
    sensor.set_pixformat(Sensor.RGB565, chn=CAM_CHN_ID_0)

    Display.init(Display.VIRT, width=FRAME_W, height=FRAME_H, to_ide=True)
    MediaManager.init()
    sensor.run()

    while True:
        os.exitpoint()

        img  = sensor.snapshot(chn=CAM_CHN_ID_0)
        jpeg = img.compress(quality=JPEG_QUALITY)
        send_frame(udp_sock, jpeg.bytearray(), FRAME_W, FRAME_H)

        print("jpeg:", len(jpeg.bytearray()), "B")

        Display.show_image(img)

except KeyboardInterrupt as e:
    print("用户停止:", e)
except BaseException as e:
    print(f"异常: {e}")
finally:
    udp_sock.close()
    if isinstance(sensor, Sensor):
        sensor.stop()
    Display.deinit()
    os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
    time.sleep_ms(100)
    MediaManager.deinit()
