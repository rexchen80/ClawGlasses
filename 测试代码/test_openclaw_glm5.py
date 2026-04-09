import time
import re
import pyautogui
import pyperclip
from zai import ZhipuAiClient

def run_agent(instruction: str, api_key: str):
    print("初始化 ZhipuAiClient...")
    client = ZhipuAiClient(api_key=api_key)
    
    system_prompt = """你是一个类似OpenClaw的AI计算机控制代理。
你需要将用户的自然语言指令转换为一段可以在Windows上运行的Python代码。
请遵循以下规则：
1. 使用 pyautogui 库和 time 库来控制鼠标和键盘。
2. 遇到需要输入中文字符或复杂字符串的情况，必须使用 pyperclip 库将文本复制到剪贴板，然后使用 pyautogui.hotkey('ctrl', 'v') 粘贴，因为 pyautogui.write 不支持直接输入中文。
3. 每一步操作之间必须有足够的 time.sleep() 等待时间（例如打开软件后等待2-3秒，输入文字后等待1秒），以确保软件有时间响应。
4. 使用 'win' 键呼出开始菜单并搜索程序名称来打开程序，是最稳妥的方法。例如打开Chrome：按 win，等待1秒，输入 chrome，等待1秒，回车。
5. 在浏览器中搜索时，最好在地址栏直接输入或者进入主页后再搜索。如果是进入百度，输入 www.baidu.com 然后回车，等待加载完毕，再粘贴搜索词并回车。
6. 只返回包含在 ```python 和 ``` 之间的 Python 代码块，不要有任何其他解释或注释，代码必须可直接执行。
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"指令：{instruction}"}
    ]

    print("思考中，正在调用 GLM-5.1 生成操作代码...")
    try:
        response = client.chat.completions.create(
            model="glm-5.1",
            messages=messages,
            thinking={
                "type": "enabled",
            },
            max_tokens=8192,
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        print("\n================== 模型生成内容 ==================")
        print(content)
        print("==================================================\n")
        
        # 提取代码
        code_match = re.search(r'```python\s*(.*?)\s*```', content, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            print("即将执行以下代码：\n")
            print(code)
            print("\n--- 开始执行操作 ---")
            
            # 安全防范：给用户5秒钟的时间确认
            print("⚠️ 警告：5秒后将自动接管鼠标键盘，请勿移动鼠标！(Ctrl+C 取消)")
            time.sleep(5)
            
            try:
                exec(code, globals())
                print("--- 执行操作完毕 ---")
            except Exception as e:
                print(f"执行代码出错: {e}")
        else:
            print("未找到Python代码块。模型返回内容格式可能不正确。")
            
    except Exception as e:
        print(f"API 请求失败: {e}")

if __name__ == "__main__":
    # 使用用户提供的 API Key
    api_key = "8a6239a1e42f3c2411f39b1926f0fcb7.Q6bU8id0xQyGHFIz"
    instruction = "打开Chrome浏览器，搜索'希尔顿大床房'"
    print(f"当前任务: {instruction}")
    run_agent(instruction, api_key)
