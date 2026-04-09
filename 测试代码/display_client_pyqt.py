import sys
import socket
import json
import threading
import queue
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QDesktopWidget
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

class OverlayApp(QWidget):
    def __init__(self, client_id):
        super().__init__()
        self.client_id = str(client_id)
        self.show_border = False
        self.current_text = ""
        
        # Configure window properties for overlay
        # Frameless, Always on top, Tool window (no taskbar icon), Transparent background
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool | 
            Qt.WindowTransparentForInput  # This enables click-through on both Mac and Win!
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Get screen dimensions
        screen = QDesktopWidget().screenGeometry()
        self.setGeometry(screen)
        
        # UI Setup for Subtitle
        self.layout = QVBoxLayout()
        self.layout.addStretch()  # Push subtitle to bottom
        
        self.subtitle_label = QLabel("")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        
        # Subtitle styling
        font = QFont("Arial", 48, QFont.Bold)
        self.subtitle_label.setFont(font)
        
        # We use a stylesheet for the text outline effect (text-shadow equivalent)
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: white;
                background-color: transparent;
                /* Simulated outline using shadow */
            }
        """)
        
        self.layout.addWidget(self.subtitle_label)
        self.layout.setContentsMargins(0, 0, 0, 100) # Margin from bottom
        self.setLayout(self.layout)
        
        # Queue for thread-safe communication
        self.msg_queue = queue.Queue()
        
        # Start UDP broadcast receiver thread
        self.udp_thread = threading.Thread(target=self.udp_receiver_thread, daemon=True)
        self.udp_thread.start()
        
        # Timer to poll the queue (UI thread)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(50)  # Check every 50ms

    def paintEvent(self, event):
        # Custom drawing for the border and text outline
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw Border
        if self.show_border:
            pen = QPen(QColor("red"))
            pen.setWidth(5)
            painter.setPen(pen)
            # Draw slightly inside to ensure visibility
            rect = self.rect().adjusted(2, 2, -2, -2)
            painter.drawRect(rect)
            
        # Draw Text with Outline manually since QLabel stylesheet text-shadow is limited
        if self.current_text:
            font = QFont("Arial", 48, QFont.Bold)
            painter.setFont(font)
            
            # Position for text (bottom center)
            text_rect = self.rect().adjusted(0, 0, 0, -100)
            
            # Draw outline
            outline_pen = QPen(QColor("black"))
            outline_pen.setWidth(2)
            painter.setPen(outline_pen)
            
            # Draw text multiple times offset slightly to create thick outline
            outline_width = 4
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx*dx + dy*dy <= outline_width*outline_width:
                        painter.drawText(text_rect.translated(dx, dy), Qt.AlignBottom | Qt.AlignHCenter, self.current_text)
            
            # Draw main text
            painter.setPen(QPen(QColor("white")))
            painter.drawText(text_rect, Qt.AlignBottom | Qt.AlignHCenter, self.current_text)
            
        # Hide the QLabel text since we draw it manually for better outline
        self.subtitle_label.setText("")

    def udp_receiver_thread(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
                
        sock.bind(("", 37020))
        
        print("====================================")
        print("UDP 广播接收端已启动！正在监听端口 37020 ...")
        print(f"本机 ID 设置为: {self.client_id}")
        print("====================================")
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode('utf-8'))
                msg['_sender_ip'] = addr[0]
                self.msg_queue.put(msg)
            except Exception as e:
                print(f"UDP 接收错误: {e}")

    def process_queue(self):
        update_needed = False
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                event = msg.get('event')
                content = msg.get('data')
                sender_ip = msg.get('_sender_ip', '未知IP')
                
                print(f"[收到广播] 来自 {sender_ip} -> 事件: {event}, 内容: {content}")
                
                if event == 'lookat':
                    target_id = str(content)
                    new_border_state = (target_id == self.client_id)
                    if self.show_border != new_border_state:
                        self.show_border = new_border_state
                        update_needed = True
                        
                elif event == 'prompt':
                    new_text = str(content)
                    if self.current_text != new_text:
                        self.current_text = new_text
                        update_needed = True
                        
        except queue.Empty:
            pass
            
        if update_needed:
            self.update()  # Trigger repaint

def main():
    if len(sys.argv) < 2:
        print("用法: python display_client.py <本机ID>")
        print("例如: python display_client.py 1")
        sys.exit(1)
        
    client_id = sys.argv[1]
    
    app = QApplication(sys.argv)
    overlay = OverlayApp(client_id)
    overlay.show()
    
    print("按 Ctrl+C 或在终端关闭程序")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
