import asyncio
from openai import AsyncOpenAI

async def main():
    print("正在初始化 OpenAI 客户端，连接本地 OpenClaw 网关...")
    # 连接本地正常运行的网关（兼容 OpenAI 接口）
    # 大多数本地网关需要 /v1 后缀，如果 OpenClaw 不需要，可以移除 /v1
    ai = AsyncOpenAI(
        base_url="http://127.0.0.1:18789/v1", 
        api_key="sk-local-test"  # 本地测试通常不需要真实的 key，但 openai SDK 规定必填
    )
    
    try:
        print("正在发送指令: '法国的首都是哪里？'")
        # 发送你的指令
        result = await ai.chat.completions.create(
            model="openclaw:main",
            messages=[{"role": "user", "content": "法国的首都是哪里？"}]
        )
        
        print("\n网关返回结果:")
        print(result.choices[0].message.content)
        
    except Exception as e:
        print(f"\n请求失败: {e}")
        print("--> 请确认本地的 OpenClaw 网关（127.0.0.1:18789）已经启动并正在运行。")

# 运行
asyncio.run(main())
