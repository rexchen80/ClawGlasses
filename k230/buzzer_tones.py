# buzzer_tones.py
#
# LCKFB 庐山派 K230 蜂鸣器音效库
# 硬件连接：GPIO43 -> PWM1
# 优化：精简逻辑、扩展音符、苹果风格升降调
#

import time
from machine import PWM, FPIOA

# ──────────────────────────────────────────
#  音符频率表（科学音调记号法，Hz）
# ──────────────────────────────────────────
C5 = 523  # Do (中央C)
D5 = 587  # Re
E5 = 659  # Mi
F5 = 698  # Fa
G5 = 784  # Sol
A5 = 880  # La
B5 = 988  # Si
C6 = 1047  # 高音Do

# ──────────────────────────────────────────
#  音效序列定义
#  格式：(频率Hz, 持续ms, 间隔ms)
# ──────────────────────────────────────────

# 1. 开机/连网成功：四音上升 C5→E5→G5→C6，清脆上扬
_WIFI_SUCCESS = [
    (C5, 120, 20),
    (E5, 120, 20),
    (G5, 120, 20),
    (C6, 180, 0),
]

# 2. 操作提示：单音短促 G5，干净利落
_NOTIFY = [
    (G5, 100, 0),
]

# 3. 错误/警告：两音下降 G5→C5，低沉警示
_ERROR = [
    (G5, 150, 50),
    (C5, 200, 0),
]


class BuzzerTones:
    """庐山派 K230 无源蜂鸣器音效播放器"""

    # 对外暴露的音效常量
    WIFI_SUCCESS = _WIFI_SUCCESS
    NOTIFY = _NOTIFY
    ERROR = _ERROR

    def __init__(self):
        # 初始化引脚复用和PWM
        fpioa = FPIOA()
        fpioa.set_function(43, FPIOA.PWM1)
        self._pwm = PWM(1)
        self._pwm.duty_u16(0)  # 初始静音

    def _beep(self, freq, duration_ms):
        """内部方法：播放单音"""
        self._pwm.freq(freq)
        self._pwm.duty_u16(32768)  # 50%占空比（音量适中）
        time.sleep_ms(duration_ms)
        self._pwm.duty_u16(0)  # 停止发声

    def play(self, sequence):
        """播放一组音效序列"""
        for freq, duration, gap in sequence:
            self._beep(freq, duration)
            if gap > 0:
                time.sleep_ms(gap)

    def deinit(self):
        """释放PWM资源"""
        self._pwm.duty_u16(0)
        self._pwm.deinit()


# ──────────────────────────────────────────
#  演示代码（直接运行可测试音效）
# ──────────────────────────────────────────
if __name__ == "__main__":
    tone = BuzzerTones()

    print("▶ 播放：连网成功")
    tone.play(tone.WIFI_SUCCESS)
    time.sleep_ms(800)

    print("▶ 播放：操作提示")
    tone.play(tone.NOTIFY)
    time.sleep_ms(600)

    print("▶ 播放：错误警告")
    tone.play(tone.ERROR)
    time.sleep_ms(600)

    tone.deinit()
    print("✅ 演示完毕")
