import threading
import numpy as np
import sounddevice as sd
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from pynput import keyboard

# ──────────────────────────────────────────────
#  配置
# ──────────────────────────────────────────────
DASHSCOPE_API_KEY = "sk-24f77dddb77049de9cca8917b82a50b2"
ASR_MODEL = "fun-asr-realtime-2026-02-28"
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 3200  # 每块帧数（约100ms @ 16kHz int16）

# ──────────────────────────────────────────────
#  全局状态
# ──────────────────────────────────────────────
is_recording = False
recognition = None  # 当前 Recognition 实例
rec_lock = threading.Lock()
rec_ready = threading.Event()  # WebSocket 连接就绪后 set

# ──────────────────────────────────────────────
#  初始化 dashscope
# ──────────────────────────────────────────────
dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

print()
print("=" * 55)
print("  使用说明（阿里云百炼实时语音识别）")
print("  · 按住 [空格键] 开始录音并实时识别")
print("  · 松开 [空格键] 停止本次识别")
print("  · 按 [Ctrl+C] 或 [ESC] 退出")
print("=" * 55)
print()


# ──────────────────────────────────────────────
#  ASR 回调
# ──────────────────────────────────────────────
class ASRCallback(RecognitionCallback):
    def on_open(self) -> None:
        rec_ready.set()

    def on_close(self) -> None:
        pass

    def on_complete(self) -> None:
        pass

    def on_error(self, message) -> None:
        print(f"\r[ASR错误] {message.message}        ")

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if sentence and "text" in sentence and sentence["text"]:
            if RecognitionResult.is_sentence_end(sentence):
                print(f"\r识别结果: {sentence['text']}        ")
            else:
                print(f"\r[识别中] {sentence['text']}...", end="", flush=True)


# ──────────────────────────────────────────────
#  音频回调（sounddevice InputStream）
# ──────────────────────────────────────────────
def audio_callback(indata: np.ndarray, frames: int, time_info, status):
    if not is_recording or not rec_ready.is_set():
        return
    rec = recognition
    if rec is not None:
        recognition.send_audio_frame(indata.tobytes())


# ──────────────────────────────────────────────
#  开始/停止识别
# ──────────────────────────────────────────────
def start_recognition():
    global recognition
    rec_ready.clear()
    cb = ASRCallback()
    rec = Recognition(
        model=ASR_MODEL,
        format="pcm",
        sample_rate=SAMPLE_RATE,
        semantic_punctuation_enabled=False,
        callback=cb,
    )
    with rec_lock:
        recognition = rec
    rec.start()


def stop_recognition():
    global recognition
    rec_ready.clear()
    with rec_lock:
        rec = recognition
        recognition = None
    if rec is not None:
        threading.Thread(target=rec.stop, daemon=True).start()


# ──────────────────────────────────────────────
#  键盘监听
# ──────────────────────────────────────────────
space_pressed = False


def on_press(key):
    global is_recording, space_pressed
    if key == keyboard.Key.space and not space_pressed:
        space_pressed = True
        is_recording = True
        print("\r[录音中...]               ", end="", flush=True)
        threading.Thread(target=start_recognition, daemon=True).start()

    if key == keyboard.Key.esc:
        return False


def on_release(key):
    global is_recording, space_pressed
    if key == keyboard.Key.space:
        space_pressed = False
        if is_recording:
            is_recording = False
            stop_recognition()


# ──────────────────────────────────────────────
#  主程序
# ──────────────────────────────────────────────
def main():
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=audio_callback,
        blocksize=BLOCK_SIZE,
    )
    stream.start()

    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    except KeyboardInterrupt:
        pass
    finally:
        stop_recognition()
        stream.stop()
        stream.close()
        print("\n\n[*] 程序已退出")


if __name__ == "__main__":
    main()
