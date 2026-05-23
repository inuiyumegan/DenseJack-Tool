import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable

DEFAULT_FUZZY_RANGE_MS = 50
DEFAULT_K_COUNT = 4
MAX_K_COUNT = 10
OSU_PLAYFIELD_WIDTH = 512
HITOBJ_CIRCLE = 1
HITOBJ_HOLD = 128
QUARTER_NOTE_DIVISOR = 4
MILLISECONDS_PER_MINUTE = 60_000
SUFFIX_TAG = " [DenseJack Ver]"
APP_TITLE = "DenseJack Tool v0.63 by 幽幽子的饲养员"
BPM_SCALE_OPTIONS = {"1倍速": 1.0, "1.5倍速": 1.5, "2倍速": 2.0}
TIME_SHIFT_OPTIONS = ("不变", "向前移一格", "向后移一格")

def safe_int(s: str, default: int = 0) -> int:
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return default

def safe_float(s: str) -> float | None:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None

def find_section_index(lines: list[str], section: str) -> int | None:
    target = f"[{section}]"
    for i, line in enumerate(lines):
        if line.strip() == target:
            return i
    return None

def update_version_tag(lines: list[str]) -> None:
    in_meta = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[Metadata]":
            in_meta = True
            continue
        if in_meta:
            if stripped.startswith("[") and stripped != "[Metadata]":
                break
            if stripped.lower().startswith("version:"):
                lines[i] = line.rstrip() + SUFFIX_TAG
                break

def extract_bpm(lines: list[str]) -> float | None:
    idx = find_section_index(lines, "TimingPoints")
    if idx is None:
        return None
    for i in range(idx + 1, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith("["):
            break
        parts = line.split(",")
        if len(parts) >= 7:
            beatlen = safe_float(parts[1])
            inherited = safe_int(parts[6])
            if inherited == 1 and beatlen is not None and beatlen > 0:
                return MILLISECONDS_PER_MINUTE / beatlen
    return None

def detect_key_count(lines: list[str], ho_idx: int) -> int:
    x_set: set[int] = set()
    for i in range(ho_idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("["):
            break
        parts = s.split(",")
        if len(parts) < 5:
            continue
        x_val = safe_int(parts[0])
        if x_val:
            x_set.add(x_val)
    if not x_set:
        return DEFAULT_K_COUNT
    k = len(x_set)
    if k < DEFAULT_K_COUNT:
        return DEFAULT_K_COUNT
    if k > MAX_K_COUNT:
        return MAX_K_COUNT
    return k

class HitObject:
    __slots__ = ("x", "time", "end_time", "obj_type")
    def __init__(self, x: int, time: int, obj_type: int, end_time: int = 0):
        self.x = x
        self.time = time
        self.obj_type = obj_type
        self.end_time = end_time

def parse_hitobjects(lines: list[str], ho_idx: int) -> tuple[list[HitObject], list[HitObject]]:
    clicks: list[HitObject] = []
    holds: list[HitObject] = []
    for i in range(ho_idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("["):
            break
        parts = s.split(",")
        if len(parts) < 5:
            continue
        x = safe_int(parts[0])
        t0 = safe_int(parts[2])
        obj_type = safe_int(parts[3])
        if obj_type == HITOBJ_HOLD and len(parts) >= 6:
            end_time = safe_int(parts[5].split(":")[0])
            t1 = min(t0, end_time)
            t2 = max(t0, end_time)
            holds.append(HitObject(x, t1, obj_type, end_time=t2))
        elif obj_type == HITOBJ_CIRCLE:
            clicks.append(HitObject(x, t0, obj_type))
    return clicks, holds

def generate_lanes(k_count: int) -> list[str]:
    base_step = OSU_PLAYFIELD_WIDTH / (k_count * 2)
    return [str(int(base_step * (2 * i + 1))) for i in range(k_count)]

def generate_candidates(lanes: list[str], t_start: int, t_end: int, quarter_gap: float) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    now = t_start
    while now <= t_end:
        t_rounded = int(round(now))
        for x in lanes:
            candidates.append((x, t_rounded))
        now += quarter_gap
    return candidates

def match_and_block(
    candidates: list[tuple[str, int]],
    clicks: list[HitObject],
    holds: list[HitObject],
    fuzzy_range: int,
) -> set[int]:
    blocked: set[int] = set()

    for click in clicks:
        best_idx: int | None = None
        best_diff = 99999
        for i, (cx, ct) in enumerate(candidates):
            if cx != str(click.x):
                continue
            d = abs(ct - click.time)
            if d <= fuzzy_range and d < best_diff:
                best_diff = d
                best_idx = i
        if best_idx is not None:
            blocked.add(best_idx)

    for hold in holds:
        x_str = str(hold.x)
        start_idx: int | None = None
        end_idx: int | None = None
        best_d1 = 99999
        best_d2 = 99999
        for i, (cx, ct) in enumerate(candidates):
            if cx != x_str:
                continue
            d1 = abs(ct - hold.time)
            d2 = abs(ct - hold.end_time)
            if d1 <= fuzzy_range and d1 < best_d1:
                best_d1 = d1
                start_idx = i
            if d2 <= fuzzy_range and d2 < best_d2:
                best_d2 = d2
                end_idx = i
        if start_idx is not None and end_idx is not None:
            a = min(start_idx, end_idx)
            b = max(start_idx, end_idx)
            for i in range(a, b + 1):
                if candidates[i][0] == x_str:
                    blocked.add(i)
    return blocked

def apply_time_shift(
    candidates: list[tuple[str, int]],
    blocked: set[int],
    quarter_gap: float,
    shift_option: str,
) -> list[str]:
    shift_map: dict[str, float] = {
        "向前移一格": -quarter_gap,
        "向后移一格": quarter_gap,
    }
    delta = shift_map.get(shift_option, 0.0)
    result: list[str] = []
    for i, (x, t) in enumerate(candidates):
        if i not in blocked:
            new_t = int(round(t + delta))
            result.append(f"{x},192,{new_t},1,0,0:0:0:0:")
    return result

def save_output(lines: list[str], ho_idx: int, notes: list[str], osu_path: str) -> str:
    output = lines[:ho_idx + 1] + notes
    folder = os.path.dirname(osu_path)
    fname = os.path.basename(osu_path)
    new_fname = fname[:-4] + SUFFIX_TAG + ".osu"
    save_path = os.path.join(folder, new_fname)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output) + "\n")
    return save_path

def process_single(
    osu_path: str,
    bpm_scale: float,
    custom_bpm: str,
    fuzzy_range: int,
    time_shift_opt: str,
) -> tuple[bool, str]:
    try:
        with open(osu_path, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]

        update_version_tag(lines)

        if custom_bpm.strip():
            final_bpm = safe_float(custom_bpm)
            if final_bpm is None:
                return False, "自定义BPM格式错误"
        else:
            bpm = extract_bpm(lines)
            if bpm is None:
                return False, "BPM 识别失败"
            final_bpm = bpm * bpm_scale

        ho_idx = find_section_index(lines, "HitObjects")
        if ho_idx is None:
            return False, "未找到 [HitObjects]"

        k_count = detect_key_count(lines, ho_idx)
        clicks, holds = parse_hitobjects(lines, ho_idx)

        all_times = [h.time for h in clicks] + [h.time for h in holds] + [h.end_time for h in holds]
        if not all_times:
            return False, "无音符"
        t_start = min(all_times)
        t_end = max(all_times)

        quarter_gap = MILLISECONDS_PER_MINUTE / final_bpm / QUARTER_NOTE_DIVISOR
        lanes = generate_lanes(k_count)
        candidates = generate_candidates(lanes, t_start, t_end, quarter_gap)
        blocked = match_and_block(candidates, clicks, holds, fuzzy_range)
        final_notes = apply_time_shift(candidates, blocked, quarter_gap, time_shift_opt)

        save_output(lines, ho_idx, final_notes, osu_path)

        msg = (
            f"BPM:{final_bpm:.0f} | 四分间隔:{quarter_gap:.0f}ms "
            f"| 自动识别K数:{k_count} | 偏移:{time_shift_opt}"
        )
        return True, msg

    except Exception as e:
        return False, f"错误：{e}"

class DenseJackApp:

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("580x650")
        self.root.resizable(False, False)

        self.batch_mode = tk.BooleanVar(value=False)
        self.scale_var = tk.StringVar(value="1倍速")
        self.shift_var = tk.StringVar(value="不变")

        self._build_ui()

    def _build_ui(self) -> None:
        g1 = ttk.LabelFrame(self.root, text="转换模式")
        g1.pack(padx=20, pady=8, fill="x")
        ttk.Radiobutton(g1, text="单个文件", variable=self.batch_mode, value=False).pack(anchor="w", padx=16, pady=3)
        ttk.Radiobutton(g1, text="批量整个目录", variable=self.batch_mode, value=True).pack(anchor="w", padx=16, pady=3)

        g2 = ttk.LabelFrame(self.root, text="BPM 倍率")
        g2.pack(padx=20, pady=8, fill="x")
        for label in BPM_SCALE_OPTIONS:
            ttk.Radiobutton(g2, text=label, variable=self.scale_var, value=label).pack(anchor="w", padx=16, pady=3)

        g3 = ttk.LabelFrame(self.root, text="自定义BPM（填则强制单曲）")
        g3.pack(padx=20, pady=8, fill="x")
        self.entry_custom = ttk.Entry(g3)
        self.entry_custom.pack(padx=16, pady=8, fill="x")

        g4 = ttk.LabelFrame(self.root, text="模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）")
        g4.pack(padx=20, pady=8, fill="x")
        self.entry_fuzzy = ttk.Entry(g4)
        self.entry_fuzzy.insert(0, str(DEFAULT_FUZZY_RANGE_MS))
        self.entry_fuzzy.pack(padx=16, pady=8, fill="x")

        g_shift = ttk.LabelFrame(self.root, text="生成音符时间偏移（自动按当前四分音符间隔移一格）")
        g_shift.pack(padx=20, pady=8, fill="x")
        for label in TIME_SHIFT_OPTIONS:
            ttk.Radiobutton(g_shift, text=label, variable=self.shift_var, value=label).pack(anchor="w", padx=16, pady=3)

        ttk.Button(self.root, text="开始转换", command=self._on_start, width=35).pack(pady=20)

        tip_frame = ttk.Frame(self.root)
        tip_frame.pack(padx=20, pady=(0, 15), fill="x")
        tips = [
            "LN识别可能有bug，需自行修改",
            "BPM识别不准可手动填BPM重新生成",
            "批量模式下自定义BPM设置将失效",
        ]
        for tip in tips:
            ttk.Label(tip_frame, text=tip, font=("", 10, "bold")).pack(anchor="w", pady=2)

    def _on_start(self) -> None:
        custom_bpm = self.entry_custom.get().strip()
        fuzzy_range = safe_int(self.entry_fuzzy.get().strip()) or DEFAULT_FUZZY_RANGE_MS
        time_shift_opt = self.shift_var.get()
        bpm_scale = BPM_SCALE_OPTIONS.get(self.scale_var.get(), 1.0)

        if custom_bpm:
            self.batch_mode.set(False)

        if self.batch_mode.get():
            self._run_batch(bpm_scale, fuzzy_range, time_shift_opt)
        else:
            self._run_single(bpm_scale, custom_bpm, fuzzy_range, time_shift_opt)

    def _run_batch(self, bpm_scale: float, fuzzy_range: int, time_shift_opt: str) -> None:
        folder = filedialog.askdirectory(title="选择批量目录")
        if not folder:
            return
        total = 0
        ok = 0
        for name in os.listdir(folder):
            if name.lower().endswith(".osu"):
                total += 1
                full = os.path.join(folder, name)
                succ, _ = process_single(full, bpm_scale, "", fuzzy_range, time_shift_opt)
                if succ:
                    ok += 1
        messagebox.showinfo("批量完成", f"总计：{total}\n成功：{ok}")

    def _run_single(self, bpm_scale: float, custom_bpm: str, fuzzy_range: int, time_shift_opt: str) -> None:
        path = filedialog.askopenfilename(filetypes=[("osu 文件", "*.osu")])
        if not path:
            return
        succ, msg = process_single(path, bpm_scale, custom_bpm, fuzzy_range, time_shift_opt)
        messagebox.showinfo("完成" if succ else "失败", msg)

    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = DenseJackApp()
        app.run()
    except Exception:
        input("启动失败，请检查 Python / tkinter")