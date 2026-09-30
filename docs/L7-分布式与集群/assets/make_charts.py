# -*- coding: utf-8 -*-
"""Generate L7 evaluation charts as dependency-free SVG.

Data sources (all measured / official, no invented numbers):
  1. InferenceX, "DeepSeek R1 on MI355X" and "DeepSeek R1 on B200":
     https://inferencex.semianalysis.com/run/deepseek-r1-on-mi355x
     https://inferencex.semianalysis.com/run/deepseek-r1-on-b200
     Single-turn chat workload, 8k input / 1k output, best engine+precision
     at each per-user interactivity target.
  2. MLPerf Inference rules (inference_rules.adoc, early-stopping appendix):
     inferences needed for a 99% confidence interval per tail percentile.
"""
import os

# Charts are written next to this script (docs/L7-分布式与集群/assets/), so the
# script is self-contained and can be re-run from anywhere:  python make_charts.py
ASSETS = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- data

# InferenceX measured frontier, DeepSeek R1, 8k/1k single-turn chat.
TARGETS = [30, 50, 75, 100, 150, 200]
MI355X_TOK  = [1134, 1608, 4027, 3616, 1568, 413]
MI355X_COST = [0.37, 0.26, 0.10, 0.12, 0.27, 1.01]
B200_TOK    = [6799, 4610, 3172, 2685, 2146, 1598]
B200_COST   = [0.071, 0.10, 0.15, 0.18, 0.22, 0.30]

# MLPerf Inference: inferences required, 99% CI, per tail percentile.
TAIL = [("p90", 0.50, 24576), ("p95", 0.25, 57344), ("p99", 0.05, 270336)]

INK, MUTED, GRID = "#1a1d21", "#5c6570", "#e2e6ea"
BLUE, ORANGE = "#1f6feb", "#d97706"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=12, fill=INK, anchor="start", weight="400"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def line(x1, y1, x2, y2, stroke=GRID, width=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>')


def rect(x, y, w, h, fill, stroke="none", rx=0):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}"/>')


def circle(cx, cy, r, fill, stroke="#fff", sw=1.5):
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')


def svg_open(w, h, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
            f'height="{h}" role="img" aria-label="{esc(title)}" '
            f'font-family="{FONT}">\n{rect(0, 0, w, h, "#ffffff")}\n')


def lerp_color(t):
    """Not used; kept for clarity of intent if styling changes."""
    return BLUE


def fmt_int(v):
    return f"{v:,}"


# ------------------------------------------------------- chart 1: pareto

def chart_pareto():
    W, H = 1180, 560
    L, R, T, B = 78, 1074, 74, 470          # shared plot box
    X0, X1 = 25, 210                         # x data range (tok/s/user)
    Y0, Y1 = 0, 7300                         # y data range (tok/s/GPU)
    C0, C1 = 0.0, 1.10                       # cost range ($/1M tokens)

    def sx(v):
        return L + (v - X0) / (X1 - X0) * (R - L)

    def sy_tok(v):
        return B - (v - Y0) / (Y1 - Y0) * (B - T)

    def sy_cost(v):
        return B - (v - C0) / (C1 - C0) * (B - T)

    s = [svg_open(W, H, "DeepSeek R1 在 MI355X 与 B200 上的交互性-吞吐-成本前沿")]

    # titles
    s.append(text(78, 34, "交互性 vs 吞吐 vs 成本：DeepSeek R1 的实测前沿", 17, INK, weight="700"))
    s.append(text(78, 54, "8k 输入 / 1k 输出 单轮对话；每个档位取该点最优引擎与精度（InferenceX 实测）", 12, MUTED))

    # grid + y axis (throughput)
    for v in range(0, 7300, 1000):
        y = sy_tok(v)
        s.append(line(L, y, R, y))
        s.append(text(L - 10, y + 4, fmt_int(v), 11, MUTED, anchor="end"))
    s.append(text(L, T + 4, "吞吐 tok/s/GPU（左轴）", 11, MUTED))

    # x axis
    for v in TARGETS:
        x = sx(v)
        s.append(line(x, T, x, B, GRID, 1, "3 3"))
        s.append(text(x, B + 22, str(v), 11, MUTED, anchor="middle"))
    s.append(text((L + R) / 2, B + 46, "单用户生成速度 tok/s/用户（交互性目标）", 12, MUTED, anchor="middle"))

    # cost axis on right
    s.append(line(R, T, R, B, GRID))
    for v in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = sy_cost(v)
        s.append(text(R + 10, y + 4, f"${v:.2f}", 11, MUTED))
    s.append(text(R + 10, T - 16, "$/1M tokens（右轴）", 11, MUTED))

    # 50 tok/s reference band
    x50 = sx(50)
    s.append(line(x50, T, x50, B, ORANGE, 1.5, "6 4"))
    s.append(text(x50 + 8, T + 16, "50 tok/s/用户（常见交互目标）", 11, ORANGE, weight="700"))

    # throughput lines
    for series, color, name in ((MI355X_TOK, BLUE, "MI355X"), (B200_TOK, ORANGE, "B200")):
        pts = " ".join(f"{sx(t):.1f},{sy_tok(v):.1f}" for t, v in zip(TARGETS, series))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for t, v in zip(TARGETS, series):
            s.append(circle(sx(t), sy_tok(v), 4.5, color))
            s.append(text(sx(t), sy_tok(v) - 12, fmt_int(v), 10, color, anchor="middle", weight="700"))

    # cost lines (dashed, on right axis)
    for series, color in ((MI355X_COST, BLUE), (B200_COST, ORANGE)):
        pts = " ".join(f"{sx(t):.1f},{sy_cost(v):.1f}" for t, v in zip(TARGETS, series))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" '
                 f'stroke-dasharray="5 4" opacity="0.75"/>')

    # legend
    lx, ly = L + 446, T + 26
    s.append(rect(lx, ly - 14, 246, 62, "#ffffff", GRID, 8))
    s.append(line(lx + 12, ly + 2, lx + 40, ly + 2, BLUE, 2.5))
    s.append(text(lx + 48, ly + 6, "MI355X 吞吐（左轴）", 11, INK))
    s.append(line(lx + 12, ly + 22, lx + 40, ly + 22, ORANGE, 2.5))
    s.append(text(lx + 48, ly + 26, "B200 吞吐（左轴）", 11, INK))
    s.append(line(lx + 12, ly + 42, lx + 40, ly + 42, MUTED, 1.6, "5 4"))
    s.append(text(lx + 48, ly + 46, "两者 $/1M tokens（右轴）", 11, MUTED))

    # annotations: placed in empty space, with leaders to the points they name
    def arrow(x1, y1, x2, y2, color):
        return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="2 3" opacity="0.85"/>')

    # MI355X: peak at 75 tok/s, and the cliff at 200 tok/s
    s.append(arrow(sx(75), sy_tok(4027) + 22, sx(75) + 6, sy_tok(4027) - 4, BLUE))
    s.append(text(sx(75) + 12, sy_tok(4027) + 30, "MI355X 峰值在 75 tok/s", 10.5, BLUE, weight="700"))
    s.append(arrow(sx(200) - 6, sy_tok(413) - 16, sx(190), sy_tok(900), BLUE))
    s.append(text(sx(196), sy_tok(1050), "过 100 tok/s 后急剧下滑", 10.5, BLUE, weight="700", anchor="end"))
    # B200: monotonic decline, label under the curve at mid-range
    s.append(text(sx(93), sy_tok(1900), "B200 随交互性提高单调下降", 10.5, ORANGE, weight="700"))

    s.append("</svg>\n")
    return "".join(s)


# ------------------------------------------------- chart 2: tail cost

def chart_tail_cost():
    W, H = 1180, 430
    L, R, T, B = 96, 1080, 84, 320
    MAXV = 300000.0

    def sy(v):
        return B - (v / MAXV) * (B - T)

    s = [svg_open(W, H, "MLPerf 尾延迟分位与所需推断次数")]
    s.append(text(96, 34, "尾巴越靠后，测量成本涨得越快", 17, INK, weight="700"))
    s.append(text(96, 54, "MLPerf Inference 规则：达到 99% 置信区间所需的最少推断次数", 12, MUTED))

    n = len(TAIL)
    slot = (R - L) / n
    bw = slot * 0.42
    for i, (name, moe, cnt) in enumerate(TAIL):
        cx = L + slot * (i + 0.5)
        x = cx - bw / 2
        y = sy(cnt)
        color = BLUE if name != "p99" else ORANGE
        s.append(rect(x, y, bw, B - y, color, rx=6))
        s.append(text(cx, y - 26, fmt_int(cnt), 14, color, anchor="middle", weight="700"))
        s.append(text(cx, y - 10, f"±{moe:.2f}%", 11, MUTED, anchor="middle"))
        s.append(text(cx, B + 24, name, 14, INK, anchor="middle", weight="700"))

    # baseline + ratio annotations
    s.append(line(L, sy(24576), R, sy(24576), MUTED, 1, "4 4"))
    s.append(text(L + 6, sy(24576) - 8, "以 p90 为基准", 10.5, MUTED))
    for i, (name, moe, cnt) in enumerate(TAIL):
        if i == 0:
            continue
        cx = L + slot * (i + 0.5)
        ratio = cnt / 24576
        s.append(text(cx, B + 46, f"≈ {ratio:.1f}× p90 的样本量", 11, MUTED, anchor="middle"))

    s.append(line(L, B, R, B, GRID, 1.5))
    s.append("</svg>\n")
    return "".join(s)


# --------------------------------------------- chart 3: scaling efficiency

# MLPerf Inference v6.1, datacenter-closed, deepseek-r1, Server scenario,
# total tokens/s measured on real submissions (summary.xlsx).
# (accelerators, total tokens/s)
SCALE_SERIES = [
    ("GB300 NVL72 · NVIDIA 8→72→288", "#1f6feb",
     [(8, 67578.3), (72, 596944.0), (288, 2028030.0)], True),
    ("GB200 NVL72 · Azure 72→288", "#0f7b3f",
     [(72, 426796.0), (288, 1598510.0)], False),
    ("GB200 NVL72 · CoreWeave 8→72", "#a12c6b",
     [(8, 56121.3), (72, 419778.0)], True),
    ("B300 · Cisco 8→16", "#d97706",
     [(8, 66171.6), (16, 88915.5)], True),
]
SINGLE_NODE_PER_GPU = 67578.3 / 8          # the 8-GPU GB300 single-node point


def chart_scaling():
    W, H = 1180, 620
    L1, R1 = 88, 560          # left panel (per-GPU throughput)
    L2, R2 = 690, 1130        # right panel (efficiency)
    T, B = 104, 512
    XMIN, XMAX = 6.0, 600.0   # accelerator count, log scale

    import math

    def lx(a, L, R):
        return L + (math.log10(a) - math.log10(XMIN)) / (math.log10(XMAX) - math.log10(XMIN)) * (R - L)

    def ly(v, Y0, Y1):
        return B - (math.log10(v) - math.log10(Y0)) / (math.log10(Y1) - math.log10(Y0)) * (B - T)

    def ey(e):
        return B - (e - 0) / 120.0 * (B - T)

    s = [svg_open(W, H, "MLPerf DeepSeek-R1 多卡扩展：每卡吞吐与扩展效率")]
    s.append(text(88, 34, "扩展效率：同一模型加卡后，每张卡还剩多少产能", 17, INK, weight="700"))
    s.append(text(88, 54, "MLPerf Inference v6.1 · DeepSeek-R1 · Server 场景实测（总吞吐换算成每卡）", 12, MUTED))

    # ---- left panel: per-GPU throughput, log scale
    s.append(text(L1, T - 12, "每卡吞吐 tokens/s（对数轴）", 11.5, INK, weight="700"))
    for v in [4000, 7000, 10000, 20000, 40000, 70000]:
        y = ly(v, 3000, 100000)
        s.append(line(L1, y, R1, y))
        s.append(text(L1 - 8, y + 4, fmt_int(v), 10.5, MUTED, anchor="end"))
    for a in [8, 16, 36, 72, 288]:
        x = lx(a, L1, R1)
        s.append(line(x, T, x, B, GRID, 1, "3 3"))
        s.append(text(x, B + 20, str(a), 10.5, MUTED, anchor="middle"))
    s.append(text((L1 + R1) / 2, B + 42, "加速卡数量（对数轴）", 11.5, MUTED, anchor="middle"))

    # single-node reference: what one 8-GPU node does per GPU
    yr = ly(SINGLE_NODE_PER_GPU, 3000, 100000)
    s.append(line(L1, yr, R1, yr, "#a05a00", 1.4, "6 4"))
    s.append(text(L1 + 6, yr - 8, f"单机 8 卡每卡水平 ≈ {SINGLE_NODE_PER_GPU:,.0f}", 10.5, "#a05a00", weight="700"))

    for name, color, pts, solid in SCALE_SERIES:
        coords = [(lx(a, L1, R1), ly(t / a, 3000, 100000)) for a, t in pts]
        if len(coords) > 1:
            d = "" if solid else ' stroke-dasharray="6 4"'
            p = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            s.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="2.4"{d}/>')
        for (a, t), (x, y) in zip(pts, coords):
            s.append(circle(x, y, 4.2, color))
    # label the GB300 jump
    gx, gy = lx(288, L1, R1), ly(2028030 / 288, 3000, 100000)
    s.append(text(gx + 10, gy + 4, f"{2028030/288:,.0f} tok/s/卡", 10.5, "#1f6feb",
                  weight="700", anchor="start"))

    # ---- right panel: efficiency relative to each system's own baseline
    s.append(text(L2, T - 12, "扩展效率（各自以最小规模为 100%）", 11.5, INK, weight="700"))
    for e in [0, 20, 40, 60, 80, 100, 120]:
        y = ey(e)
        s.append(line(L2, y, R2, y, GRID if e != 100 else "#a05a00", 1,
                      None if e == 100 else None))
        s.append(text(L2 - 8, y + 4, f"{e}%", 10.5, MUTED, anchor="end"))
    for a in [8, 16, 72, 288]:
        x = lx(a, L2, R2)
        s.append(text(x, B + 20, str(a), 10.5, MUTED, anchor="middle"))
    s.append(text((L2 + R2) / 2, B + 42, "加速卡数量（对数轴）", 11.5, MUTED, anchor="middle"))
    s.append(text(L2 + 6, ey(100) - 8, "100% = 线性扩展", 10.5, "#a05a00", weight="700"))

    for name, color, pts, solid in SCALE_SERIES:
        base_pg = pts[0][1] / pts[0][0]
        coords = [(lx(a, L2, R2), ey((t / a) / base_pg * 100)) for a, t in pts]
        if len(coords) > 1:
            d = "" if solid else ' stroke-dasharray="6 4"'
            p = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            s.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="2.4"{d}/>')
            # fill under the curve to make the gap from 100% visible
            fill = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            s.append(f'<polygon points="{fill} {coords[-1][0]:.1f},{ey(0):.1f} {coords[0][0]:.1f},{ey(0):.1f}" '
                     f'fill="{color}" opacity="0.07"/>')
        for (a, t), (x, y) in zip(pts, coords):
            s.append(circle(x, y, 4.2, color))
            if a == pts[-1][0] and len(pts) > 1:
                eff = (t / a) / base_pg * 100
                anchor = "end" if a >= 200 else "start"
                dx = -8 if anchor == "end" else 8
                s.append(text(x + dx, y - 10, f"{eff:.0f}%", 11, color, weight="700", anchor=anchor))

    # legend (below the left panel, inside canvas)
    lgx, lgy = L1, B + 62
    for i, (name, color, pts, solid) in enumerate(SCALE_SERIES):
        col = i % 2
        row = i // 2
        x = lgx + col * 320
        y = lgy + row * 22
        d = '' if solid else ' stroke-dasharray="6 4"'
        s.append(f'<line x1="{x}" y1="{y}" x2="{x+26}" y2="{y}" stroke="{color}" stroke-width="2.4"{d}/>')
        s.append(text(x + 34, y + 4, name, 11, INK))

    s.append("</svg>\n")
    return "".join(s)


# ------------------------------------------------------------- write

def write(name, content):
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"{name}  {len(content)} bytes")


os.makedirs(ASSETS, exist_ok=True)
write("chart-pareto-frontier.svg", chart_pareto())
write("chart-tail-sample-cost.svg", chart_tail_cost())
write("chart-scaling-efficiency.svg", chart_scaling())
