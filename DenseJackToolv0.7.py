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
APP_TITLE = "DenseJack Tool v0.71 by 幽幽子的饲养员"
BPM_SCALE_OPTIONS = {"1倍速": 1.0, "1.5倍速": 1.5, "2倍速": 2.0}
TIME_SHIFT_OPTIONS = ("不变", "向前移一格", "向后移一格")

# ── 中英文翻译表（key 为中文原文，value 为 {zh, en}） ──
_TR = {
    "转换模式":            {"zh": "转换模式",            "en": "Mode"},
    "单个文件":            {"zh": "单个文件",            "en": "Single File"},
    "批量整个目录":        {"zh": "批量整个目录",        "en": "Batch Folder"},
    "BPM 倍率":            {"zh": "BPM 倍率",            "en": "BPM Rate"},
    "自定义BPM（填则强制单曲）": {"zh": "自定义BPM（填则强制单曲）", "en": "Custom BPM (forces single mode)"},
    "手动指定K数（0=自动识别）": {"zh": "手动指定K数（0=自动识别）", "en": "Manual Key Count (0=auto)"},
    "模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）": {
        "zh": "模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）",
        "en": "Fuzzy Range ms (match & remove nearest note within range)"},
    "生成音符时间偏移（自动按当前四分音符间隔移一格）": {
        "zh": "生成音符时间偏移（自动按当前四分音符间隔移一格）",
        "en": "Time Shift (auto shift by one quarter-note grid)"},
    "不变":                {"zh": "不变",                "en": "Keep"},
    "向前移一格":          {"zh": "向前移一格",          "en": "Forward ×1"},
    "向后移一格":          {"zh": "向后移一格",          "en": "Backward ×1"},
    "开始转换":            {"zh": "开始转换",            "en": "Start"},
    "LN识别可能有bug，需自行修改": {"zh": "LN识别可能有bug，需自行修改", "en": "LN detection may be buggy, manual fix needed"},
    "BPM识别不准可手动填BPM重新生成": {"zh": "BPM识别不准可手动填BPM重新生成", "en": "If BPM is off, manually enter BPM and re-generate"},
    "批量模式下自定义BPM设置将失效": {"zh": "批量模式下自定义BPM设置将失效", "en": "Custom BPM is ignored in batch mode"},
    "选择批量目录":        {"zh": "选择批量目录",        "en": "Select Batch Folder"},
    "批量完成":            {"zh": "批量完成",            "en": "Batch Complete"},
    "总计：":              {"zh": "总计：",              "en": "Total: "},
    "成功：":              {"zh": "成功：",              "en": "OK: "},
    "完成":                {"zh": "完成",                "en": "Done"},
    "失败":                {"zh": "失败",                "en": "Failed"},
    "自定义BPM格式错误":   {"zh": "自定义BPM格式错误",   "en": "Invalid custom BPM format"},
    "BPM 识别失败":        {"zh": "BPM 识别失败",        "en": "BPM detection failed"},
    "未找到 [HitObjects]": {"zh": "未找到 [HitObjects]", "en": "[HitObjects] not found"},
    "无音符":              {"zh": "无音符",              "en": "No notes found"},
    "osu 文件":            {"zh": "osu 文件",            "en": "osu file"},
    "错误：":              {"zh": "错误：",              "en": "Error: "},
}

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

def extract_circle_size(lines: list[str]) -> int | None:
    """从 [Difficulty] 读取 CircleSize，osu!mania 下即键数。"""
    idx = find_section_index(lines, "Difficulty")
    if idx is None:
        return None
    for i in range(idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("["):
            break
        if s.lower().startswith("circlesize:"):
            val = safe_int(s.split(":", 1)[1])
            if val:
                return val
    return None

def detect_key_count(lines: list[str], ho_idx: int) -> int:
    # 优先使用 [Difficulty] 的 CircleSize（mania 下即键数）
    cs = extract_circle_size(lines)
    if cs is not None and DEFAULT_K_COUNT <= cs <= MAX_K_COUNT:
        return cs

    # 回退：通过 HitObject X 坐标去重估算
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
            # 将 X 坐标四舍五入到最接近的 512/k 轨道的中心
            x_set.add(x_val)
    if not x_set:
        return DEFAULT_K_COUNT
    # 聚类相近的 X 值：把相差 <=8 的归为同一列
    sorted_x = sorted(x_set)
    clusters = 1
    for j in range(1, len(sorted_x)):
        if sorted_x[j] - sorted_x[j - 1] > 8:
            clusters += 1
    k = clusters
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
        if (obj_type & HITOBJ_HOLD) and len(parts) >= 6:
            end_time = safe_int(parts[5].split(":")[0])
            t1 = min(t0, end_time)
            t2 = max(t0, end_time)
            holds.append(HitObject(x, t1, obj_type, end_time=t2))
        elif (obj_type & HITOBJ_CIRCLE):
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

def _snap_x(x: int, lane_ints: list[int], fuzzy_range: int) -> int | None:
    """将 X 坐标吸附到最近的轨道中心，仅在 fuzzy_range 像素内生效；超出则返回 None。"""
    best = min(lane_ints, key=lambda lx: abs(lx - x))
    return best if abs(best - x) <= fuzzy_range else None

def match_and_block(
    candidates: list[tuple[str, int]],
    clicks: list[HitObject],
    holds: list[HitObject],
    fuzzy_range: int,
    lanes: list[str],
) -> set[int]:
    lane_ints = [int(l) for l in lanes]
    blocked: set[int] = set()

    for click in clicks:
        best_idx: int | None = None
        best_diff = 99999
        snapped = _snap_x(click.x, lane_ints, fuzzy_range)
        if snapped is None:
            continue
        snapped_x = str(snapped)
        for i, (cx, ct) in enumerate(candidates):
            if cx != snapped_x:
                continue
            d = abs(ct - click.time)
            if d <= fuzzy_range and d < best_diff:
                best_diff = d
                best_idx = i
        if best_idx is not None:
            blocked.add(best_idx)

    for hold in holds:
        snapped = _snap_x(hold.x, lane_ints, fuzzy_range)
        if snapped is None:
            continue
        snapped_x = str(snapped)
        start_idx: int | None = None
        end_idx: int | None = None
        best_d1 = 99999
        best_d2 = 99999
        for i, (cx, ct) in enumerate(candidates):
            if cx != snapped_x:
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
                if candidates[i][0] == snapped_x:
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
    k_override: int = 0,
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

        k_count = k_override if k_override else detect_key_count(lines, ho_idx)
        clicks, holds = parse_hitobjects(lines, ho_idx)

        all_times = [h.time for h in clicks] + [h.time for h in holds] + [h.end_time for h in holds]
        if not all_times:
            return False, "无音符"
        t_start = min(all_times)
        t_end = max(all_times)

        quarter_gap = MILLISECONDS_PER_MINUTE / final_bpm / QUARTER_NOTE_DIVISOR
        lanes = generate_lanes(k_count)
        candidates = generate_candidates(lanes, t_start, t_end, quarter_gap)
        blocked = match_and_block(candidates, clicks, holds, fuzzy_range, lanes)
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
        self.root.geometry("680x780")
        self.root.resizable(True, True)

        self.lang = "zh"  # zh / en
        self._text_widgets: list[tuple[tk.Widget, str]] = []  # (widget, tr_key) for dynamic refresh

        self.batch_mode = tk.BooleanVar(value=False)
        self.scale_var = tk.StringVar(value="1倍速")
        self.shift_var = tk.StringVar(value="向前移一格")

        self._build_ui()

    # ── 翻译工具 ──
    def t(self, key: str) -> str:
        """根据当前语言返回翻译文本。"""
        entry = _TR.get(key)
        if entry:
            return entry.get(self.lang, key)
        return key

    def _reg(self, widget: tk.Widget, key: str) -> None:
        """注册需要动态刷新文本的控件。"""
        self._text_widgets.append((widget, key))

    def _toggle_lang(self) -> None:
        """中英文切换。"""
        self.lang = "en" if self.lang == "zh" else "zh"
        self._lang_btn.config(text="中" if self.lang == "en" else "EN")
        self._refresh_texts()

    def _refresh_texts(self) -> None:
        """遍历所有注册控件，刷新文本内容。"""
        for widget, key in self._text_widgets:
            txt = self.t(key)
            try:
                widget.configure(text=txt)
            except Exception:
                pass  # 控件可能已被销毁或不支持 text 属性

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        # 语言切换按钮
        top_bar = ttk.Frame(self.root)
        top_bar.pack(padx=20, pady=(10, 0), fill="x")
        self._lang_btn = ttk.Button(top_bar, text="EN", command=self._toggle_lang, width=4)
        self._lang_btn.pack(side="right")

        g1 = ttk.LabelFrame(self.root, text=self.t("转换模式"))
        self._reg(g1, "转换模式")
        g1.pack(padx=20, pady=8, fill="x")
        rb1 = ttk.Radiobutton(g1, text=self.t("单个文件"), variable=self.batch_mode, value=False)
        self._reg(rb1, "单个文件")
        rb1.pack(anchor="w", padx=16, pady=3)
        rb2 = ttk.Radiobutton(g1, text=self.t("批量整个目录"), variable=self.batch_mode, value=True)
        self._reg(rb2, "批量整个目录")
        rb2.pack(anchor="w", padx=16, pady=3)

        g2 = ttk.LabelFrame(self.root, text=self.t("BPM 倍率"))
        self._reg(g2, "BPM 倍率")
        g2.pack(padx=20, pady=8, fill="x")
        self._scale_rbs: list[ttk.Radiobutton] = []
        for label in BPM_SCALE_OPTIONS:
            rb = ttk.Radiobutton(g2, text=label, variable=self.scale_var, value=label)
            rb.pack(anchor="w", padx=16, pady=3)
            self._scale_rbs.append(rb)

        g3 = ttk.LabelFrame(self.root, text=self.t("自定义BPM（填则强制单曲）"))
        self._reg(g3, "自定义BPM（填则强制单曲）")
        g3.pack(padx=20, pady=8, fill="x")
        self.entry_custom = ttk.Entry(g3)
        self.entry_custom.pack(padx=16, pady=8, fill="x")

        gk = ttk.LabelFrame(self.root, text=self.t("手动指定K数（0=自动识别）"))
        self._reg(gk, "手动指定K数（0=自动识别）")
        gk.pack(padx=20, pady=8, fill="x")
        self.entry_k = ttk.Entry(gk)
        self.entry_k.insert(0, "0")
        self.entry_k.pack(padx=16, pady=8, fill="x")

        g4 = ttk.LabelFrame(self.root, text=self.t("模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）"))
        self._reg(g4, "模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）")
        g4.pack(padx=20, pady=8, fill="x")
        self.entry_fuzzy = ttk.Entry(g4)
        self.entry_fuzzy.insert(0, str(DEFAULT_FUZZY_RANGE_MS))
        self.entry_fuzzy.pack(padx=16, pady=8, fill="x")

        g_shift = ttk.LabelFrame(self.root, text=self.t("生成音符时间偏移（自动按当前四分音符间隔移一格）"))
        self._reg(g_shift, "生成音符时间偏移（自动按当前四分音符间隔移一格）")
        g_shift.pack(padx=20, pady=8, fill="x")
        self._shift_rbs: list[ttk.Radiobutton] = []
        for raw_label in TIME_SHIFT_OPTIONS:
            rb = ttk.Radiobutton(g_shift, text=self.t(raw_label), variable=self.shift_var, value=raw_label)
            self._reg(rb, raw_label)
            rb.pack(anchor="w", padx=16, pady=3)
            self._shift_rbs.append(rb)

        self._start_btn = ttk.Button(self.root, text=self.t("开始转换"), command=self._on_start, width=35)
        self._reg(self._start_btn, "开始转换")
        self._start_btn.pack(pady=10)

        tip_frame = ttk.Frame(self.root)
        tip_frame.pack(padx=20, pady=(0, 15), fill="x")
        self._tip_labels: list[ttk.Label] = []
        tip_keys = [
            "LN识别可能有bug，需自行修改",
            "BPM识别不准可手动填BPM重新生成",
            "批量模式下自定义BPM设置将失效",
        ]
        for key in tip_keys:
            lbl = ttk.Label(tip_frame, text=self.t(key), font=("", 10, "bold"))
            self._reg(lbl, key)
            lbl.pack(anchor="w", pady=2)
            self._tip_labels.append(lbl)

    # ── 事件处理 ──
    def _on_start(self) -> None:
        custom_bpm = self.entry_custom.get().strip()
        fuzzy_range = safe_int(self.entry_fuzzy.get().strip()) or DEFAULT_FUZZY_RANGE_MS
        time_shift_opt = self.shift_var.get()
        bpm_scale = BPM_SCALE_OPTIONS.get(self.scale_var.get(), 1.0)
        k_override = safe_int(self.entry_k.get().strip()) or 0

        if custom_bpm:
            self.batch_mode.set(False)

        if self.batch_mode.get():
            self._run_batch(bpm_scale, fuzzy_range, time_shift_opt, k_override)
        else:
            self._run_single(bpm_scale, custom_bpm, fuzzy_range, time_shift_opt, k_override)

    def _run_batch(self, bpm_scale: float, fuzzy_range: int, time_shift_opt: str, k_override: int = 0) -> None:
        folder = filedialog.askdirectory(title=self.t("选择批量目录"))
        if not folder:
            return
        total = 0
        ok = 0
        for name in os.listdir(folder):
            if name.lower().endswith(".osu"):
                total += 1
                full = os.path.join(folder, name)
                succ, _ = process_single(full, bpm_scale, "", fuzzy_range, time_shift_opt, k_override)
                if succ:
                    ok += 1
        messagebox.showinfo(self.t("批量完成"),
                            f"{self.t('总计：')}{total}\n{self.t('成功：')}{ok}")

    def _run_single(self, bpm_scale: float, custom_bpm: str, fuzzy_range: int, time_shift_opt: str, k_override: int = 0) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("osu 文件"), "*.osu")])
        if not path:
            return
        succ, msg_raw = process_single(path, bpm_scale, custom_bpm, fuzzy_range, time_shift_opt, k_override)
        # 翻译 process_single 返回的消息
        msg = self._translate_result_msg(msg_raw)
        messagebox.showinfo(self.t("完成") if succ else self.t("失败"), msg)

    def _translate_result_msg(self, msg: str) -> str:
        """将 process_single 返回的中文消息按当前语言翻译。"""
        for zh_text, entry in _TR.items():
            if zh_text in msg:
                msg = msg.replace(zh_text, entry.get(self.lang, zh_text))
        return msg

    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = DenseJackApp()
        app.run()
    except Exception:
        input("启动失败，请检查 Python / tkinter")