import tkinter as tk
import ctypes

# Constants for Windows API
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20

def set_clickthrough(hwnd):
    """Make the window transparent to mouse clicks."""
    GetWindowLong = ctypes.windll.user32.GetWindowLongW
    SetWindowLong = ctypes.windll.user32.SetWindowLongW
    
    style = GetWindowLong(hwnd, GWL_EXSTYLE)
    style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    SetWindowLong(hwnd, GWL_EXSTYLE, style)

def create_overlay():
    root = tk.Tk()
    
    # Configure window properties
    root.overrideredirect(True)  # Remove window borders and title bar
    root.attributes('-topmost', True)  # Always on top
    root.attributes('-transparentcolor', 'black')  # Set black as the transparent color
    
    # Get screen dimensions
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    
    # Set window to cover the entire screen
    root.geometry(f"{screen_width}x{screen_height}+0+0")
    root.configure(bg='black')
    
    # Create canvas for drawing
    canvas = tk.Canvas(root, width=screen_width, height=screen_height, bg='black', highlightthickness=0)
    canvas.pack()
    
    # Draw 5px red border around the screen edge
    # The coordinates are slightly inset to ensure the border is fully visible
    border_width = 5
    offset = border_width // 2
    canvas.create_rectangle(offset, offset, 
                            screen_width - offset - 1, screen_height - offset - 1, 
                            outline='red', width=border_width)
    
    # Draw "Hello World" subtitle
    font = ("Microsoft YaHei", 48, "bold")
    text = "Hello World"
    x = screen_width // 2
    y = screen_height - 150  # Position it near the bottom
    
    # Draw text outline (black) - made very thick
    outline_width = 10
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            # Use a circular mask to ensure the thick outline has smooth, rounded corners
            if dx*dx + dy*dy <= outline_width*outline_width:
                canvas.create_text(x + dx, y + dy, text=text, font=font, fill='black', justify='center')
            
    # Draw main text (white)
    canvas.create_text(x, y, text=text, font=font, fill='white', justify='center')
    
    # Apply the click-through effect
    root.update()
    
    # Get the top-level window handle (HWND) for the tkinter window
    # wm_frame() returns a string containing the hex representation of the HWND
    hwnd = int(root.wm_frame(), 16)
    
    set_clickthrough(hwnd)
    
    root.mainloop()

if __name__ == "__main__":
    create_overlay()
