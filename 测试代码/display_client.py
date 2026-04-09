import tkinter as tk
import socket
import json
import sys
import threading
import queue

# Platform specific imports and click-through functions
if sys.platform == 'win32':
    import ctypes
    # Constants for Windows API
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020121
    GWL_EXSTYLE = -20

    def set_clickthrough(hwnd):
        """Make the window transparent to mouse clicks (Windows only)."""
        GetWindowLong = ctypes.windll.user32.GetWindowLongW
        SetWindowLong = ctypes.windll.user32.SetWindowLongW
        
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        SetWindowLong(hwnd, GWL_EXSTYLE, style)
else:
    def set_clickthrough(hwnd):
        # macOS / Linux fallback
        print("[提示] 当前系统非 Windows，暂不支持原生鼠标穿透功能，请避免在全屏时点击屏幕。")

class OverlayApp:
    def __init__(self, root, client_id):
        self.root = root
        self.client_id = str(client_id)
        
        # Configure window properties
        self.root.overrideredirect(True)  # Remove window borders and title bar
        self.root.attributes('-topmost', True)  # Always on top
        
        # Platform specific transparency settings
        if sys.platform == 'win32':
            self.root.attributes('-transparentcolor', 'black')  # Set black as the transparent color
            self.bg_color = 'black'
        elif sys.platform == 'darwin':
            self.root.attributes('-transparent', True)
            self.bg_color = 'systemTransparent'
        else:
            self.bg_color = 'black'
            
        # Get screen dimensions
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # Set window to cover the entire screen
        self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")
        self.root.configure(bg=self.bg_color)
        
        # Create canvas for drawing
        self.canvas = tk.Canvas(self.root, width=self.screen_width, height=self.screen_height, bg=self.bg_color, highlightthickness=0)
        self.canvas.pack()
        
        # Border settings
        self.border_width = 5
        self.offset = self.border_width // 2
        self.border_rect = None
        
        # Text settings
        self.font = ("Microsoft YaHei", 48, "bold") if sys.platform == 'win32' else ("Arial", 48, "bold")
        self.text_x = self.screen_width // 2
        self.text_y = self.screen_height - 150  # Position it near the bottom
        self.text_outline_ids = []
        self.text_main_id = None
        self.current_text = None
        
        # Queue for thread-safe communication
        self.msg_queue = queue.Queue()
        
        # Start UDP broadcast receiver thread
        self.udp_thread = threading.Thread(target=self.udp_receiver_thread, daemon=True)
        self.udp_thread.start()
        
        # Start polling the queue
        self.root.after(100, self.process_queue)
        
        # Apply the click-through effect
        self.root.update()
        if sys.platform == 'win32':
            hwnd = int(self.root.wm_frame(), 16)
            set_clickthrough(hwnd)
        else:
            set_clickthrough(None)

    def draw_border(self, show):
        if show:
            if self.border_rect is None:
                self.border_rect = self.canvas.create_rectangle(
                    self.offset, self.offset, 
                    self.screen_width - self.offset - 1, self.screen_height - self.offset - 1, 
                    outline='red', width=self.border_width)
        else:
            if self.border_rect is not None:
                self.canvas.delete(self.border_rect)
                self.border_rect = None

    def update_subtitle(self, text):
        if text == self.current_text:
            return
            
        self.current_text = text
        
        # Clear old text
        for item_id in self.text_outline_ids:
            self.canvas.delete(item_id)
        self.text_outline_ids.clear()
        
        if self.text_main_id is not None:
            self.canvas.delete(self.text_main_id)
            self.text_main_id = None
            
        if not text:
            return

        # Draw text outline (black) - made very thick
        outline_width = 10
        # On Windows, pure 'black' is the transparent color, so use slightly off-black for outline to prevent seeing through the text
        outline_color = '#000001' if sys.platform == 'win32' else 'black'
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx*dx + dy*dy <= outline_width*outline_width:
                    item_id = self.canvas.create_text(
                        self.text_x + dx, self.text_y + dy, 
                        text=text, font=self.font, fill=outline_color, justify='center'
                    )
                    self.text_outline_ids.append(item_id)
                
        # Draw main text (white)
        self.text_main_id = self.canvas.create_text(
            self.text_x, self.text_y, 
            text=text, font=self.font, fill='white', justify='center'
        )

    def udp_receiver_thread(self):
        # 配置 UDP 广播接收
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 允许端口复用（如果在一台电脑上开多个客户端，不会报端口占用错误）
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
                
        # 绑定到所有可用网卡，监听 37020 端口
        sock.bind(("", 37020))
        
        print("====================================")
        print("UDP 广播接收端已启动！正在监听端口 37020 ...")
        print(f"本机 ID 设置为: {self.client_id}")
        print("====================================")
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode('utf-8'))
                # 记录发送者IP
                msg['_sender_ip'] = addr[0]
                self.msg_queue.put(msg)
            except Exception as e:
                print(f"UDP 接收错误: {e}")

    def process_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                event = msg.get('event')
                content = msg.get('data')
                sender_ip = msg.get('_sender_ip', '未知IP')
                
                print(f"[收到广播] 来自 {sender_ip} -> 事件: {event}, 内容: {content}")
                
                if event == 'lookat':
                    target_id = str(content)
                    if target_id == self.client_id:
                        self.draw_border(True)
                    else:
                        self.draw_border(False)
                elif event == 'prompt':
                    self.update_subtitle(str(content))
                    
        except queue.Empty:
            pass
            
        # Schedule next check
        self.root.after(50, self.process_queue)

def main():
    if len(sys.argv) < 2:
        print("用法: python display_client.py <本机ID>")
        print("例如: python display_client.py 1")
        sys.exit(1)
        
    client_id = sys.argv[1]
    
    root = tk.Tk()
    app = OverlayApp(root, client_id)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\n客户端已退出")

if __name__ == "__main__":
    main()
