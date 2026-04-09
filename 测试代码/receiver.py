import zmq
import sys

# 默认连本机的发送端，如果局域网其他电脑接收，可通过命令行参数传入 IP，例如：python receiver.py 192.168.1.100
SERVER_IP = "127.0.0.1"
if len(sys.argv) > 1:
    SERVER_IP = sys.argv[1]

# 1. 配置 ZeroMQ SUB (订阅者模式)
context = zmq.Context()
sock = context.socket(zmq.SUB)
sock.connect(f"tcp://{SERVER_IP}:37020")
sock.setsockopt_string(zmq.SUBSCRIBE, "")  # "" 表示订阅该端口的所有事件消息

print("====================================")
print(f"ZMQ 接收端已启动！正在尝试连接 {SERVER_IP}:37020 ...")
print("====================================")

try:
    # 2. 持续可靠接收消息
    while True:
        # recv_json() 会阻塞直到收到完整数据，ZMQ 底层确保 100% 不丢包、不乱序
        msg = sock.recv_json()
        event = msg.get('event')
        content = msg.get('data')
        print(f"[可靠接收] IP: {SERVER_IP} -> 事件: {event}, 内容: {content}")
except KeyboardInterrupt:
    print("\n接收端已退出")
