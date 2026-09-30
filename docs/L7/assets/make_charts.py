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

# Charts are written next to this script (docs/L7/assets/), so the script is
# self-contained and can be re-run from anywhere:  python make_charts.py
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


# ------------------------------------------------------------- write

def write(name, content):
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"{name}  {len(content)} bytes")


os.makedirs(ASSETS, exist_ok=True)
write("chart-pareto-frontier.svg", chart_pareto())
write("chart-tail-sample-cost.svg", chart_tail_cost())
