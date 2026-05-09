import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

def auto_detect_k(lines, ho_idx):
    x_set = set()
    for i in range(ho_idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith('['):
            break
        parts = s.split(',')
        if len(parts) < 5:
            continue
        try:
            x = int(parts[0].strip())
            x_set.add(x)
        except:
            continue
    if not x_set:
        return 4
    xs = sorted(list(x_set))
    k = len(xs)

    if k < 4:
        return 4
    if k > 10:
        return 10
    return k

def process_single(osu_path, bpm_scale, custom_bpm, fuzzy_range, time_shift_opt):
    try:
        with open(osu_path, 'r', encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f.readlines()]

        in_meta = False
        for i in range(len(lines)):
            line = lines[i].strip()
            if line == "[Metadata]":
                in_meta = True
            if in_meta:
                if line.startswith('[') and line != "[Metadata]":
                    break
                if line.lower().startswith('version:'):
                    lines[i] = line.rstrip() + " [DenseJack Ver]"
                    break

        final_bpm = None
        if custom_bpm.strip():
            try:
                final_bpm = float(custom_bpm)
            except:
                return False, "自定义BPM格式错误"
        else:
            bpm = None
            in_timing = False
            for i in range(len(lines)):
                line = lines[i].strip()
                if line == "[TimingPoints]":
                    in_timing = True
                    continue
                if in_timing:
                    if not line or line.startswith('['):
                        break
                    parts = line.split(',')
                    if len(parts) >= 7:
                        try:
                            beatlen = float(parts[1])
                            uninherited = int(parts[6])
                            if uninherited == 1 and beatlen > 0:
                                bpm = 60000.0 / beatlen
                                break
                        except:
                            continue
            if bpm is None:
                return False, "BPM 识别失败"
            final_bpm = bpm * bpm_scale

        ho_idx = None
        for i in range(len(lines)):
            if lines[i].strip() == "[HitObjects]":
                ho_idx = i
                break
        if ho_idx is None:
            return False, "未找到 [HitObjects]"

        # 自动识别K数
        k_count = auto_detect_k(lines, ho_idx)

        hold_list = []
        click_list = []

        for i in range(ho_idx + 1, len(lines)):
            s = lines[i].strip()
            if not s:
                continue
            if s.startswith('['):
                break
            parts = s.split(',')
            if len(parts) < 5:
                continue

            try:
                x = parts[0].strip()
                t0 = int(parts[2])
                obj_type = int(parts[3])

                if obj_type == 128 and len(parts) >= 6:
                    end_time = int(parts[5].split(':')[0].strip())
                    t1 = min(t0, end_time)
                    t2 = max(t0, end_time)
                    hold_list.append((x, t1, t2))
                elif obj_type == 1:
                    click_list.append((x, t0))
            except:
                continue

        all_old_times = [t for (x, t) in click_list] + [t1 for (x, t1, t2) in hold_list] + [t2 for (x, t1, t2) in hold_list]
        if not all_old_times:
            return False, "无音符"
        t_start = min(all_old_times)
        t_end = max(all_old_times)

        quarter_gap = 60000.0 / final_bpm / 4
        step = quarter_gap

        base_step = 512 / (k_count * 2)
        lanes = []
        for i in range(k_count):
            lane_x = base_step * (2 * i + 1)
            lanes.append(str(int(lane_x)))

        candidate = []
        now = t_start
        while now <= t_end:
            tg = int(round(now))
            for x in lanes:
                candidate.append((x, tg))
            now += step

        blocked = set()

        for (x, t) in click_list:
            best = None
            best_diff = 99999
            for i, (cx, ct) in enumerate(candidate):
                if cx != x:
                    continue
                d = abs(ct - t)
                if d <= fuzzy_range and d < best_diff:
                    best_diff = d
                    best = i
            if best is not None:
                blocked.add(best)

        for (x, t1, t2) in hold_list:
            start_note = None
            end_note = None
            best_d1 = 99999
            best_d2 = 99999

            for i, (cx, ct) in enumerate(candidate):
                if cx != x:
                    continue
                d = abs(ct - t1)
                if d <= fuzzy_range and d < best_d1:
                    best_d1 = d
                    start_note = i

            for i, (cx, ct) in enumerate(candidate):
                if cx != x:
                    continue
                d = abs(ct - t2)
                if d <= fuzzy_range and d < best_d2:
                    best_d2 = d
                    end_note = i

            if start_note is not None and end_note is not None:
                a = min(start_note, end_note)
                b = max(start_note, end_note)
                for i in range(a, b + 1):
                    cx, ct = candidate[i]
                    if cx == x:
                        blocked.add(i)

        final_notes = []
        for i, (x, t) in enumerate(candidate):
            if i not in blocked:
                if time_shift_opt == "向前移一格":
                    new_t = int(round(t - quarter_gap))
                elif time_shift_opt == "向后移一格":
                    new_t = int(round(t + quarter_gap))
                else:
                    new_t = t
                final_notes.append(f"{x},192,{new_t},1,0,0:0:0:0:")

        output = lines[:ho_idx + 1]
        output.extend(final_notes)
        folder = os.path.dirname(osu_path)
        fname = os.path.basename(osu_path)
        new_fname = fname[:-4] + " [DenseJack Ver].osu"
        save_path = os.path.join(folder, new_fname)

        with open(save_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output) + '\n')

        return True, f"BPM:{final_bpm:.0f} | 四分间隔:{quarter_gap:.0f}ms | 自动识别K数:{k_count} | 偏移:{time_shift_opt}"

    except Exception as e:
        return False, f"错误：{str(e)}"

def start():
    custom_bpm = entry_custom.get().strip()
    fuzzy_str = entry_fuzzy.get().strip()
    fuzzy_range = 50
    try:
        if fuzzy_str:
            fuzzy_range = int(fuzzy_str)
    except:
        fuzzy_range = 50

    time_shift_opt = shift_var.get()

    if custom_bpm:
        batch_mode.set(False)

    selected = scale_var.get()
    mul = 1.0
    if selected == "1.5倍速":
        mul = 1.5
    if selected == "2倍速":
        mul = 2.0

    if batch_mode.get():
        folder = filedialog.askdirectory(title="选择批量目录")
        if not folder:
            return
        total = 0
        ok = 0
        for name in os.listdir(folder):
            if name.lower().endswith(".osu"):
                total += 1
                full = os.path.join(folder, name)
                succ, _ = process_single(full, mul, "", fuzzy_range, time_shift_opt)
                if succ:
                    ok += 1
        messagebox.showinfo("批量完成", f"总计：{total}\n成功：{ok}")
    else:
        path = filedialog.askopenfilename(filetypes=[("osu 文件", "*.osu")])
        if path:
            succ, msg = process_single(path, mul, custom_bpm, fuzzy_range, time_shift_opt)
            messagebox.showinfo("完成" if succ else "失败", msg)

try:
    root = tk.Tk()
    root.title("DenseJack Tool v0.62 by 幽幽子的饲养员")
    root.geometry("580x650")
    root.resizable(False, False)

    batch_mode = tk.BooleanVar(value=False)
    scale_var = tk.StringVar(value="1倍速")
    shift_var = tk.StringVar(value="不变")

    group1 = ttk.LabelFrame(root, text="转换模式")
    group1.pack(padx=20, pady=8, fill="x")
    ttk.Radiobutton(group1, text="单个文件", variable=batch_mode, value=False).pack(anchor="w", padx=16, pady=3)
    ttk.Radiobutton(group1, text="批量整个目录", variable=batch_mode, value=True).pack(anchor="w", padx=16, pady=3)

    group2 = ttk.LabelFrame(root, text="BPM 倍率")
    group2.pack(padx=20, pady=8, fill="x")
    ttk.Radiobutton(group2, text="1倍速", variable=scale_var, value="1倍速").pack(anchor="w", padx=16, pady=3)
    ttk.Radiobutton(group2, text="1.5倍速", variable=scale_var, value="1.5倍速").pack(anchor="w", padx=16, pady=3)
    ttk.Radiobutton(group2, text="2倍速", variable=scale_var, value="2倍速").pack(anchor="w", padx=16, pady=3)

    group3 = ttk.LabelFrame(root, text="自定义BPM（填则强制单曲）")
    group3.pack(padx=20, pady=8, fill="x")
    entry_custom = ttk.Entry(group3)
    entry_custom.pack(padx=16, pady=8, fill="x")

    group4 = ttk.LabelFrame(root, text="模糊匹配范围 ms（匹配并删除模糊范围内最近的note，看不懂可保持默认值）")
    group4.pack(padx=20, pady=8, fill="x")
    entry_fuzzy = ttk.Entry(group4)
    entry_fuzzy.insert(0, "50")
    entry_fuzzy.pack(padx=16, pady=8, fill="x")

    group_shift = ttk.LabelFrame(root, text="生成音符时间偏移（自动按当前四分音符间隔移一格）")
    group_shift.pack(padx=20, pady=8, fill="x")
    ttk.Radiobutton(group_shift, text="不变", variable=shift_var, value="不变").pack(anchor="w", padx=16, pady=3)
    ttk.Radiobutton(group_shift, text="向前移一格", variable=shift_var, value="向前移一格").pack(anchor="w", padx=16, pady=3)
    ttk.Radiobutton(group_shift, text="向后移一格", variable=shift_var, value="向后移一格").pack(anchor="w", padx=16, pady=3)

    ttk.Button(root, text="开始转换", command=start, width=35).pack(pady=20)

    tip_frame = ttk.Frame(root)
    tip_frame.pack(padx=20, pady=(0, 15), fill="x")
    
    ttk.Label(tip_frame, text="LN识别可能有bug，需自行修改", font=("",10,"bold")).pack(anchor="w", pady=2)
    ttk.Label(tip_frame, text="BPM识别不准可手动填BPM重新生成", font=("",10,"bold")).pack(anchor="w", pady=2)
    ttk.Label(tip_frame, text="批量模式下自定义BPM设置将失效", font=("",10,"bold")).pack(anchor="w", pady=1)

    root.mainloop()
except:
    input("启动失败，请检查 Python / tkinter")