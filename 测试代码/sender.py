import socket
import json
import keyboard

# 1. 配置 UDP 广播发送端
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

def send_msg(event, data):
    msg = json.dumps({"event": event, "data": data}).encode('utf-8')
    try:
        # 发送广播到局域网的 37020 端口
        sock.sendto(msg, ("<broadcast>", 37020))
        print(f"[广播发送] 事件: {event}, 内容: {data}")
    except Exception as e:
        print(f"发送失败: {e}")

print("====================================")
print("UDP 广播发送端已启动！正在监听键盘按键...")
print("====================================")
print("按 1, 2, 3 发送 lookat 事件")
print("按 q, w, e 发送 prompt 事件")
print("按 ESC 退出程序")
print("====================================")

# 2. 绑定按键事件
keyboard.on_press_key('1', lambda _: send_msg('lookat', '1'))
keyboard.on_press_key('2', lambda _: send_msg('lookat', '2'))
keyboard.on_press_key('3', lambda _: send_msg('lookat', '3'))
keyboard.on_press_key('q', lambda _: send_msg('prompt', '蹦舅'))
keyboard.on_press_key('w', lambda _: send_msg('prompt', '我要验牌'))
keyboard.on_press_key('e', lambda _: send_msg('prompt', '给我擦皮鞋'))

try:
    keyboard.wait('esc')
    print("程序已退出")
except KeyboardInterrupt:
    print("\n程序已退出")
