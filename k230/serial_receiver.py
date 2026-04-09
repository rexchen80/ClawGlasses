"""
PC 端 WiFi UDP 视频接收 + MediaPipe 单眼眼动追踪
依赖: pip install opencv-python numpy mediapipe
用法: python serial_receiver.py [--port 5566] [--scale 2.0] [--eye right|left]

协议（与 camera.py 一致）：
  帧头包:  frag_id=0xFFFF  [0xFFFF:2][0:2][LEN:4][W:2][H:2]  12字节
  数据分片: [frag_id:2][frag_total:2][JPEG数据...]

眼动追踪说明：
  使用 FaceMesh refine_landmarks，虹膜中心点相对眼角归一化坐标
  水平：左/中/右（iris_x < 0.46 / 0.46~0.65 / >0.65）
  垂直：上/中/下（iris_y < 0.46 / 0.46~0.65 / >0.65）
"""

import struct
import threading
import queue
import time
import argparse
import socket
import json

import numpy as np
import cv2
import mediapipe as mp
import sounddevice as sd
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from PIL import Image, ImageDraw, ImageFont

HEADER_MAGIC = 0xFFFF

# ── ASR 语音识别配置 ──────────────────────────────────────
DASHSCOPE_API_KEY = "sk-24f77dddb77049de9cca8917b82a50b2"
ASR_MODEL = "fun-asr-realtime-2026-02-28"
ASR_SAMPLE_RATE = 16000
ASR_CHANNELS = 1
ASR_BLOCK_SIZE = 3200
VOICE_TIMEOUT = 2.0  # 秒，无语音自动取消

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

# ── FaceMesh 关键点索引 ────────────────────────────
# 右眼（镜头视角，人脸左眼）
R_INNER   = 133   # 右眼内眼角
R_OUTER   = 33    # 右眼外眼角
R_TOP     = 159   # 右眼上眼睐
R_BOT     = 145   # 右眼下眼睐
R_IRIS    = 468   # 右眼虹膜中心（需 refine_landmarks=True）

# 左眼（镜头视角，人脸右眼）
L_INNER   = 362
L_OUTER   = 263
L_TOP     = 386
L_BOT     = 374
L_IRIS    = 473

# 眼部轮廓关键点（MediaPipe FaceMesh 眼部轮廓点集）
R_CONTOUR = [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246]
L_CONTOUR = [362,382,381,380,374,373,390,249,263,466,388,387,386,385,384,398]
# 虹膜轮廓（468~472=右虹膜，473~477=左虹膜）
R_IRIS_CONTOUR = [468, 469, 470, 471, 472]
L_IRIS_CONTOUR = [473, 474, 475, 476, 477]

GAZE_THRESH_H = 0.46   # 水平归一化阈值
GAZE_THRESH_V = 0.46   # 垂直归一化阈值

SMOOTH_WIN = 20         # 防抖滑动窗口帧数

# 注视区域 ID 映射（0=其他，1=左上，2=右上，3=左下）
GAZE_ID = {
    "左上": 1, "右上": 2, "左下": 3,
}

GAZE_LABEL = {
    (-1, -1): "左上", (0, -1): "上",  (1, -1): "右上",
    (-1,  0): "左",   (0,  0): "中",  (1,  0): "右",
    (-1,  1): "左下", (0,  1): "下",  (1,  1): "右下",
}

# 注视区域颜色（BGR）
GAZE_COLOR = {
    "左上": (255, 200, 0), "上":  (0, 255, 0),   "右上": (0, 200, 255),
    "左":   (255, 0, 200), "中":  (255, 255, 255),"右":   (0, 100, 255),
    "左下": (200, 0, 255), "下":  (0, 0, 255),    "右下": (100, 255, 0),
}


# ── PIL 中文渲染 ────────────────────────────────────────────
_FONT_CACHE = {}


def _get_font(size):
    if size not in _FONT_CACHE:
        for name in ["msyh.ttc", "simhei.ttf", "simsun.ttc",
                     "C:/Windows/Fonts/msyh.ttc",
                     "C:/Windows/Fonts/simhei.ttf"]:
            try:
                _FONT_CACHE[size] = ImageFont.truetype(name, size)
                break
            except (IOError, OSError):
                pass
        else:
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def cv2_put_text_cn(img, text, pos, font_size, color_bgr):
    """在 BGR ndarray 上用 PIL 绘制中文，color_bgr 为 (B,G,R)"""
    color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
    rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    pil_img = Image.fromarray(rgb, mode='RGB')
    draw = ImageDraw.Draw(pil_img)
    font = _get_font(font_size)
    draw.text(pos, text, font=font, fill=color_rgb)
    result = np.ascontiguousarray(np.array(pil_img, dtype=np.uint8))
    img[:] = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)


def get_landmark_px(lm_list, idx, w, h):
    lm = lm_list[idx]
    return int(lm.x * w), int(lm.y * h)


def _analyze_one_eye(lm_list, w, h, eye='right'):
    """计算单眼原始数据，返回 (iris_px, eye_rect, norm_x, norm_y)"""
    if eye == 'right':
        inner, outer, top, bot, iris_idx = R_INNER, R_OUTER, R_TOP, R_BOT, R_IRIS
    else:
        inner, outer, top, bot, iris_idx = L_INNER, L_OUTER, L_TOP, L_BOT, L_IRIS

    ix, iy = get_landmark_px(lm_list, inner, w, h)
    ox, oy = get_landmark_px(lm_list, outer, w, h)
    tx, ty = get_landmark_px(lm_list, top,   w, h)
    bx, by = get_landmark_px(lm_list, bot,   w, h)
    px, py = get_landmark_px(lm_list, iris_idx, w, h)

    eye_w = abs(ix - ox) or 1
    eye_h = abs(ty - by) or 1
    eye_x0 = min(ix, ox)
    eye_y0 = min(ty, by)

    norm_x = (px - eye_x0) / eye_w
    norm_y = (py - eye_y0) / eye_h
    eye_rect = (eye_x0, eye_y0, eye_w, eye_h)
    return (px, py), eye_rect, norm_x, norm_y


def analyze_gaze_both(lm_list, w, h):
    """只追踪左眼，返回 (gaze_label, iris_px, eye_rect, norm_xy, eye_name)"""
    iris_px, eye_rect, nx, ny = _analyze_one_eye(lm_list, w, h, 'left')

    hx = -1 if nx < GAZE_THRESH_H else (1 if nx > 1 - GAZE_THRESH_H else 0)
    vy = -1 if ny < GAZE_THRESH_V else (1 if ny > 1 - GAZE_THRESH_V else 0)

    label = GAZE_LABEL.get((hx, vy), "中")
    return label, iris_px, eye_rect, (nx, ny), 'L'


def draw_eye_tracking(frame, gaze_label, iris_px, eye_rect, norm_xy, eye_name, lm_list=None):
    """在帧上绘制被选中的单眼眼动追踪结果，如有 lm_list 则绘制眼部关键点"""
    h, w = frame.shape[:2]
    color = GAZE_COLOR.get(gaze_label, (255, 255, 255))
    ex, ey, ew, eh = eye_rect

    # 绘制左眼轮廓和虹膜关键点
    if lm_list is not None:
        for idx in L_CONTOUR:
            px, py = get_landmark_px(lm_list, idx, w, h)
            cv2.circle(frame, (px, py), 2, (100, 180, 255), -1)
        for idx in L_IRIS_CONTOUR:
            px, py = get_landmark_px(lm_list, idx, w, h)
            cv2.circle(frame, (px, py), 3, (255, 180, 0), -1)

    cv2.rectangle(frame, (ex, ey), (ex + ew, ey + eh), color, 1)
    # 虹膜中心醒目标注：白色外圈 + 彩色内圈 + 实心点 + 十字线
    ix, iy = iris_px
    cv2.circle(frame, iris_px, 10, (255, 255, 255), 2)
    cv2.circle(frame, iris_px,  7, color,           2)
    cv2.circle(frame, iris_px,  3, color,          -1)
    cv2.line(frame, (ix - 14, iy), (ix + 14, iy), (255, 255, 255), 1)
    cv2.line(frame, (ix, iy - 14), (ix, iy + 14), (255, 255, 255), 1)

    # 注视方向标签（眼框下方），附带使用的是哪只眼
    cv2_put_text_cn(frame, f"{gaze_label}({eye_name})", (ex, ey + eh + 4), 18, color)

    # 右下角：方向仪表盘（3x3 网格）
    grid_x, grid_y, cell = w - 75, h - 75, 22
    for row in range(3):
        for col in range(3):
            hx = col - 1
            vy = row - 1
            lbl = GAZE_LABEL.get((hx, vy), "")
            cx = grid_x + col * cell + cell // 2
            cy = grid_y + row * cell + cell // 2
            is_active = (lbl == gaze_label)
            bg_color = GAZE_COLOR.get(lbl, (60, 60, 60)) if is_active else (40, 40, 40)
            cv2.rectangle(frame,
                          (grid_x + col * cell, grid_y + row * cell),
                          (grid_x + col * cell + cell, grid_y + row * cell + cell),
                          bg_color, -1)
            cv2.rectangle(frame,
                          (grid_x + col * cell, grid_y + row * cell),
                          (grid_x + col * cell + cell, grid_y + row * cell + cell),
                          (100, 100, 100), 1)
            cv2_put_text_cn(frame, lbl, (cx - 9, cy - 8), 14,
                             (255, 255, 255) if is_active else (120, 120, 120))

    # norm 坐标调试信息
    nx, ny = norm_xy
    cv2.putText(frame, f"nx:{nx:.2f} ny:{ny:.2f}",
                (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    return frame


def draw_overlay(frame, fps, total_frames, errors, gaze_label, gaze_id):
    """顶部状态栏"""
    h, w = frame.shape[:2]
    color = GAZE_COLOR.get(gaze_label, (200, 200, 200))
    cv2.rectangle(frame, (0, 0), (w, 30), (30, 30, 30), -1)
    cv2_put_text_cn(frame, f"Gaze: {gaze_label}  ID:{gaze_id}", (6, 6), 20, color)
    info = f"FPS:{fps:.1f} F:{total_frames} ERR:{errors}"
    cv2.putText(frame, info, (w - 180, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    return frame


def receive_frames(sock, frame_queue, stats):
    """后台线程：接收 UDP 分片并重组为完整帧"""
    frags = {}

    while stats['running']:
        try:
            data, _ = sock.recvfrom(65535)
        except Exception:
            continue

        if len(data) < 4:
            continue

        frag_id, frag_total = struct.unpack('>HH', data[:4])

        if frag_id == HEADER_MAGIC:
            if len(data) >= 12:
                _, _, jpeg_len, w, h = struct.unpack('>HHIHH', data[:12])
                frags = {'w': w, 'h': h}
            continue

        frags[frag_id] = data[4:]

        data_frags = {k: v for k, v in frags.items() if isinstance(k, int)}
        if len(data_frags) == frag_total:
            jpeg_data = b''.join(data_frags[i] for i in range(frag_total))
            arr   = np.frombuffer(jpeg_data, dtype=np.uint8)
            frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame_bgr is None:
                stats['errors'] += 1
                frags = {}
                continue
            stats['frames'] += 1
            frags = {}

            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    pass
            frame_queue.put(frame_bgr)


def main():
    parser = argparse.ArgumentParser(description="WiFi UDP 视频接收 + 眼动追踪")
    parser.add_argument("--port",  type=int,   default=5566,  help="监听端口（默认 5566）")
    parser.add_argument("--scale", type=float, default=2.0,   help="显示放大倍数（默认 2.0）")
    parser.add_argument("--bcast-port", type=int, default=37020, help="事件 UDP 广播端口（默认 37020）")
    parser.add_argument("--voice-timeout", type=float, default=VOICE_TIMEOUT, help="语音录制超时秒数（默认 3.0）")
    args = parser.parse_args()

    # ── MediaPipe FaceMesh 初始化 ────────────────────────────
    mp_face = mp.solutions.face_mesh
    face_mesh = mp_face.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,   # 开启虹膜关键点（468/473）
        min_detection_confidence=0.2,
        min_tracking_confidence=0.2,
    )

    # ── UDP socket ───────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(1.0)
    print(f"[INFO] 监听 UDP 端口 {args.port}，追踪双眼")
    print(f"[INFO] 按 Q 退出，按 S 保存当前帧")

    # ── 广播 socket（发送 JSON 事件，20Hz）────────────────────────
    bcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    BCAST_ADDR = ("<broadcast>", args.bcast_port)
    BCAST_INTERVAL = 1.0 / 20.0   # 20 Hz
    last_bcast_t = 0.0
    print(f"[INFO] 事件 UDP 广播端口 {args.bcast_port}，20Hz")

    def bcast_json(event, data):
        """以 JSON 格式广播消息，与 sender.py 对齐"""
        msg = json.dumps({"event": event, "data": data}).encode('utf-8')
        try:
            bcast_sock.sendto(msg, BCAST_ADDR)
        except Exception as e:
            print(f"[WARN] 广播失败: {e}")

    # ── 语音录制状态 ──────────────────────────────────────────
    voice_active = False          # 是否正在录音
    voice_lock = threading.Lock()
    voice_recognition = None
    voice_rec_ready = threading.Event()
    voice_last_text = ""          # 最终识别结果
    voice_got_text = threading.Event()  # 收到完整句子时 set
    voice_any_audio = threading.Event() # 检测到人声时 set

    class GazeASRCallback(RecognitionCallback):
        def on_open(self) -> None:
            voice_rec_ready.set()
            print("[VOICE] ASR 连接就绪")

        def on_close(self) -> None:
            pass

        def on_complete(self) -> None:
            pass

        def on_error(self, message) -> None:
            print(f"[VOICE ASR错误] {message.message}")

        def on_event(self, result: RecognitionResult) -> None:
            nonlocal voice_last_text
            sentence = result.get_sentence()
            if sentence and "text" in sentence and sentence["text"]:
                voice_any_audio.set()
                if RecognitionResult.is_sentence_end(sentence):
                    voice_last_text = sentence["text"]
                    voice_got_text.set()
                    print(f"\r[VOICE] 识别结果: {sentence['text']}")
                else:
                    print(f"\r[VOICE 识别中] {sentence['text']}...", end="", flush=True)

    def voice_audio_callback(indata: np.ndarray, frames: int, time_info, status):
        if not voice_active or not voice_rec_ready.is_set():
            return
        rec = voice_recognition
        if rec is not None:
            rec.send_audio_frame(indata.tobytes())

    # 打开麦克风输入流（持续开启，录音状态由 voice_active 控制）
    mic_stream = sd.InputStream(
        samplerate=ASR_SAMPLE_RATE,
        channels=ASR_CHANNELS,
        dtype="int16",
        callback=voice_audio_callback,
        blocksize=ASR_BLOCK_SIZE,
    )
    mic_stream.start()
    print("[INFO] 麦克风已就绪，注视 ID 1/2/3 区域触发语音录制")

    def start_voice_session(triggered_id):
        """在后台线程中运行：启动 ASR -> 等待结果或超时 -> 广播 prompt"""
        nonlocal voice_active, voice_recognition, voice_last_text
        voice_last_text = ""
        voice_rec_ready.clear()
        voice_got_text.clear()
        voice_any_audio.clear()

        cb = GazeASRCallback()
        rec = Recognition(
            model=ASR_MODEL,
            format="pcm",
            sample_rate=ASR_SAMPLE_RATE,
            semantic_punctuation_enabled=False,
            callback=cb,
        )
        voice_recognition = rec
        voice_active = True
        rec.start()
        print("[VOICE] 请说话... ({}秒超时)".format(args.voice_timeout))

        # 等待识别结果，或超时
        got = voice_got_text.wait(timeout=args.voice_timeout)
        if not got and voice_any_audio.is_set():
            # 检测到人声但句子还没结束，额外等待 2 秒让 ASR 补完
            print(f"[VOICE] 识别中，延长等待...")
            got = voice_got_text.wait(timeout=2.0)
        if got and voice_last_text.strip():
            text = voice_last_text.strip()
            bcast_json("prompt", text)
            print(f"[VOICE] 已广播 prompt: {text}")
        else:
            if not voice_any_audio.is_set():
                print(f"[VOICE] {args.voice_timeout}秒内未检测到语音，已取消")
            else:
                print(f"[VOICE] 未得到完整识别结果，已取消")

        # 停止 ASR，并进入冷却期（防止 gaze 抖动反复触发）
        nonlocal voice_cooldown_until
        voice_active = False
        voice_rec_ready.clear()
        voice_recognition = None
        voice_cooldown_until = time.time() + args.voice_timeout
        try:
            threading.Thread(target=rec.stop, daemon=True).start()
        except Exception:
            pass

    prev_trigger_id = 0          # 上一次触发的 gaze_id（用于边沿检测）
    voice_cooldown_until = 0.0    # 冷却结束时间戳，期间不允许再次触发

    frame_queue = queue.Queue(maxsize=4)
    stats = {'running': True, 'frames': 0, 'errors': 0}

    recv_thread = threading.Thread(target=receive_frames,
                                   args=(sock, frame_queue, stats),
                                   daemon=True)
    recv_thread.start()

    fps = 0.0
    fps_counter = 0
    fps_t0      = time.time()
    last_frame        = None
    gaze_label        = "无人脸"
    gaze_id           = 0
    last_gaze_label   = "无人脸"
    last_iris_px      = None
    last_eye_rect     = None
    last_norm_xy      = (0.5, 0.5)
    last_eye_name     = '?'
    smooth_buf        = []  # 防抖滑动窗口

    cv2.namedWindow("Eye Tracking", cv2.WINDOW_NORMAL)

    while True:
        try:
            frame_bgr = frame_queue.get(timeout=0.05)
            last_frame = frame_bgr.copy()

            fps_counter += 1
            elapsed = time.time() - fps_t0
            if elapsed >= 1.0:
                fps = fps_counter / elapsed
                fps_counter = 0
                fps_t0 = time.time()

        except queue.Empty:
            if last_frame is None:
                if (cv2.waitKey(1) & 0xFF) in (ord('q'), 27):
                    break
                continue
            frame_bgr = last_frame

        # ── 逆时针旋转 90°（ROTATE_90_COUNTERCLOCKWISE）────
        rotated = cv2.rotate(frame_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
        h, w = rotated.shape[:2]
        display = rotated.copy()

        rgb = cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)

        if results.multi_face_landmarks:
            lm_list = results.multi_face_landmarks[0].landmark
            raw_label, iris_px, eye_rect, norm_xy, eye_name = analyze_gaze_both(
                lm_list, w, h)
            last_gaze_label, last_iris_px, last_eye_rect = raw_label, iris_px, eye_rect
            last_norm_xy, last_eye_name = norm_xy, eye_name
            # 防抖：滑动窗口投票
            smooth_buf.append(raw_label)
            if len(smooth_buf) > SMOOTH_WIN:
                smooth_buf.pop(0)
            gaze_label = max(set(smooth_buf), key=smooth_buf.count)
            gaze_id = GAZE_ID.get(gaze_label, 0)
            display = draw_eye_tracking(display, gaze_label,
                                        iris_px, eye_rect, norm_xy, eye_name, lm_list)
        else:
            if last_iris_px is not None:
                gaze_label = last_gaze_label
                gaze_id = GAZE_ID.get(gaze_label, 0)
                display = draw_eye_tracking(display, gaze_label,
                                            last_iris_px, last_eye_rect,
                                            last_norm_xy, last_eye_name)
            else:
                gaze_label = "无人脸"
                gaze_id = 0

        display = draw_overlay(display, fps, stats['frames'],
                               stats['errors'], gaze_label, gaze_id)

        # ── 20Hz 广播 lookat 事件（JSON 格式）─────────────────
        now = time.time()
        if now - last_bcast_t >= BCAST_INTERVAL:
            last_bcast_t = now
            bcast_json("lookat", str(gaze_id))
            print(f"[GAZE] id={gaze_id}  label={gaze_label}")

            # ── 语音触发逻辑：gaze_id 1/2/3 且未在录音且不在冷却期 ────
            if gaze_id in (1, 2, 3) and gaze_id != prev_trigger_id:
                if not voice_active and time.time() >= voice_cooldown_until:
                    print(f"[VOICE] 注视区域 {gaze_label}(ID:{gaze_id}) 触发语音录制")
                    threading.Thread(target=start_voice_session, args=(gaze_id,), daemon=True).start()
            prev_trigger_id = gaze_id

        # 放大显示
        dh, dw = display.shape[:2]
        display = cv2.resize(display,
                             (int(dw * args.scale), int(dh * args.scale)),
                             interpolation=cv2.INTER_LINEAR)

        cv2.imshow("Eye Tracking", display)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s') and last_frame is not None:
            fname = f"capture_{int(time.time())}.jpg"
            cv2.imwrite(fname, display)
            print(f"[INFO] 已保存: {fname}")

    stats['running'] = False
    voice_active = False
    mic_stream.stop()
    mic_stream.close()
    face_mesh.close()
    sock.close()
    bcast_sock.close()
    cv2.destroyAllWindows()
    print(f"[INFO] 共接收 {stats['frames']} 帧，错误 {stats['errors']} 次。")


if __name__ == "__main__":
    main()
