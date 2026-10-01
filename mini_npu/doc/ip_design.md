# mini_npu IP 设计规格（v1）

| 项 | 值 |
|---|---|
| 版本 | v1.0（草案） |
| 日期 | 2026-10-01 |
| 状态 | 待评审。**本文档是设计意图，尚未落地为 RTL**；已存在的 RTL 只有 `PE` 一个模块 |
| 对应代码 | [pe.sv](../rtl/pe.sv)、[pe_tb.sv](../tb/pe_tb.sv) |
| 上游背景 | [L1 芯片与硬件](../../docs/L1-芯片与硬件/00-芯片与硬件.md)、[L2 设备可编程模型](../../docs/L2-设备可编程模型/00-设备可编程模型.md) |

**这份文档要解决什么问题。** 现在的 `PE` 只是一个算乘加的 RTL 模块，只有看懂代码的人才能用它。本文档的目标是把它变成一个**能被 CPU 通过总线配置、启动、查询、中断通知的软核 IP**——也就是让它第一次具备 L2（设备可编程模型）的形态，而不只是 L1 里的一块电路。

---

## 目录

- [一、什么是 IP](#一什么是-ip)
- [二、现状与差距](#二现状与差距)
- [三、v1 范围与约束](#三v1-范围与约束)
- [四、总体结构](#四总体结构)
- [五、AXI4-Lite 从端规格](#五axi4-lite-从端规格)
- [六、地址映射](#六地址映射)
- [七、寄存器规格](#七寄存器规格)
- [八、中断规格](#八中断规格)
- [九、存储器与数据布局](#九存储器与数据布局)
- [十、序列器](#十序列器)
- [十一、模块端口清单](#十一模块端口清单)
- [十二、错误处理](#十二错误处理)
- [十三、参数与派生约束](#十三参数与派生约束)
- [十四、软件编程模型](#十四软件编程模型)
- [十五、验证计划](#十五验证计划)
- [十六、里程碑](#十六里程碑)
- [十七、已知限制与 Plan B](#十七已知限制与-plan-b)
- [十八、术语表](#十八术语表)
- [十九、参考](#十九参考)

---

## 一、什么是 IP

这一节不涉及 mini_npu，但它是后面所有设计决定的前提：**为什么"补寄存器、CSR、中断"这件事值得做，以及做到什么程度才算做完了。**

### 1.1 字面与由来

IP = Intellectual Property，知识产权。在芯片语境里，它指的是**别人已经设计好、验证过、你可以直接拿来集成的电路块**。

这个概念之所以存在，是因为一颗 SoC 里绝大多数模块不可能自研：

| 一颗典型 SoC 里的东西 | 来源 |
|---|---|
| CPU 核 | Arm / SiFive / 自研（极少数公司） |
| DDR 控制器、PCIe 控制器 | 商业 IP 厂商（Synopsys / Cadence / 新思…） |
| PCIe / SerDes PHY | 只能买硬核，跟工艺绑定 |
| USB、以太网、显示 | 商业 IP |
| SRAM / ROM | 用 foundry 的 memory compiler **现场生成**（不算传统 IP，但性质一样：不是手写的） |
| 你自己的 NPU 计算阵列 | 自研 ← mini_npu 在这里 |

自研的只应该是**你的差异化部分**，其余全部复用。这就是 IP 存在的经济理由。

### 1.2 三种交付形态

| 形态 | 交付物 | 可改性 | 性能确定性 | 典型例子 |
|---|---|---|---|---|
| **软核（soft IP）** | 可综合 RTL（源码或加密） | 高，可改参数、可改综合策略 | 低，取决于你怎么综合和布局 | AXI 互连、DMA 引擎、**mini_npu 的目标形态** |
| **固核（firm IP）** | 门级网表 + 布局指导 | 低 | 中 | 部分高性能数据通路 |
| **硬核（hard IP）** | GDSII 版图 | 不可改 | 高，面积/功耗/时序都是确定的数字 | SerDes、PLL、DDR PHY |

规律：**越靠近模拟和工艺，越只能硬核；越靠近数字逻辑，越倾向软核。** 因为模拟电路的性能跟具体工艺角、寄生参数强绑定，换个工艺就得重做；而纯数字逻辑换工艺只是重新综合一遍。

mini_npu 是纯数字、性能要求不极端，**目标形态是软核**。这意味着：不写死工艺、不写死阵列规模、不写死位宽——全部参数化。

### 1.3 "模块"和"IP"的区别：契约

这是全节最重要的一段。代码写得好不好**不是**区别，区别在于**有没有一份不看代码就能用对的契约**。

| | 模块（module） | IP |
|---|---|---|
| 使用者 | 同一个人 / 同一个层次 | **陌生的集成者**（可能是三年后的你） |
| 接口 | 内部信号，随时可改 | 冻结的对外接口（总线 / 时钟 / 复位 / 中断） |
| 怎么控制它 | 直接拉信号 | **寄存器编程模型**（软件可见） |
| 怎么配置它 | 改代码 | 改参数 / define，**不改代码** |
| 验证到哪一步 | 功能对就行 | 功能 + lint + CDC + DFT 友好 + 时序约束 + 覆盖率 |
| 交付物 | 一个 `.sv` 文件 | RTL + SDC + 文档 + 验证环境 + **版本号** |
| 接口改错的代价 | 改一行，重新编译 | **所有集成方都要改**；如果已经流片，等下一个流片周期（几百万美元 + 几个月） |

打个软件类比：模块是"我写了个函数"，IP 是"我发布了一个库"。差别不在代码质量，而在**有没有一份别人不看实现就能用对的接口文档**。

硬件的惩罚比软件重得多：软件的接口不兼容可以发个 2.0 让用户升级；硬件的接口不兼容要**重新流片**。这就是为什么硬件接口一旦暴露给软件，就被当成冻结契约。

### 1.4 为什么"能跟 CPU 交互"是分水岭

一旦 CPU 能通过 MMIO 寄存器控制这个块，**寄存器定义就变成了硬件和软件之间的长期契约**。仓库自己在 L2 里已经记下了这条教训：

> 寄存器语义定错了 → 所有驱动都要写绕过代码。
> —— [00-设备可编程模型.md](../../docs/L2-设备可编程模型/00-设备可编程模型.md)

寄存器语义定错**不会让仿真失败**，只会让每一个驱动作者都在自己的代码里塞一段 `if (rev == 0x01) ...`。这类错误在 RTL 里查不出来，只有文档能防。

反过来说：PE 现在住在 L1（芯片与硬件）；加上 AXI4-Lite 从端 + 寄存器编程模型 + 中断之后，它才第一次有了 L2（设备可编程模型）的形态。**这就是本项目的意义所在。**

### 1.5 一个 IP 的完整交付清单

这是"什么算 IP"的可操作定义。mini_npu v1 **不要求全部完成**，但要清楚哪些是有意不做的。

| # | 交付项 | v1 是否做 | 说明 |
|---|---|---|---|
| 1 | 可综合 RTL（无 latch、无组合环、无综合警告） | ✅ | |
| 2 | 参数化 + 一组有文档的默认配置 | ✅ | R / C / A_BITS / W_BITS / ACC_BITS |
| 3 | 总线从端接口 | ✅ | AXI4-Lite |
| 4 | **寄存器手册（programmer's model）** | ✅ | 第七节 |
| 5 | 中断方案 | ✅ | 第八节 |
| 6 | 时钟 / 复位方案 | ✅ | 单时钟域；异步置位同步释放 |
| 7 | **版本寄存器**（软件可读，用于驱动匹配） | ✅ | `ID` 寄存器 |
| 8 | 集成指南（怎么连、怎么配参数） | ✅ | 本文档第四、十一、十三节 |
| 9 | 端到端验证 + 自检 | ✅ | 第十五节 |
| 10 | 时序约束（SDC） | ❌ 不做 | 属于流片阶段；但文档要说明单周期路径在哪 |
| 11 | DFT（扫描链、边界扫描） | ❌ 不做 | 需要综合工具配合；只要保证 RTL 不阻碍扫描插入即可 |
| 12 | CDC（跨时钟域检查） | ❌ 不做 | 单时钟域，不存在 CDC |
| 13 | 覆盖率收敛、形式验证 | ❌ 不做 | 学习项目，超出范围 |
| 14 | 许可证 / 加密 | ❌ 不做 | 开源学习项目 |

### 1.6 自测问题

判断一个块是"模块"还是"IP"，只需要回答一个问题：

> **如果我把这个块和一个陌生工程师，只有一个键盘，他只有这份文档——他能不能把它集成进一个 SoC 并写出驱动？**

- 能 → 它是 IP。
- 需要看 RTL 才能确定某个寄存器的行为 → 它还是模块，文档没写完。

本文档的全部目的就是让答案变成"能"。

---

## 二、现状与差距

### 2.1 `PE` 当前形态

[pe.sv](../rtl/pe.sv) 目前是一个**纯数据面模块**，51 行，接口如下：

```systemverilog
module PE #(
    parameter A_BITS   = 8,
    parameter W_BITS   = 8,
    parameter ACC_BITS = 32
) (
    input  wire clk,
    input  wire rst,                       // 同步复位
    input  wire load,
    input  reg  [A_BITS-1:0]   a,
    input  reg  [W_BITS-1:0]   w,
    input  reg  [ACC_BITS-1:0] psum_in,
    output reg  [ACC_BITS-1:0] psum_out
);
```

语义（[pe.sv:7-12](../rtl/pe.sv)）：

| `load` | 行为 |
|---|---|
| 1 | `w_inner <= w`；**`psum_out` 保持不动** |
| 0 | `psum_out <= psum_in + $signed(a) * $signed(w_inner)` |

三条对后续设计有决定性影响的现状：

1. **`load` 与 MAC 互斥。** 装载权重那一拍不做乘加，所以它不可能做成脉动阵列单元（脉动阵列要求 MAC 无条件每拍都算）。可行用法是**广播式（SIMD）阵列**，代价是每步 2 拍。
2. **`psum_in` 是纯外部输入，模块内部不含反馈。** 这一点本身是对的，但阵列层把 `psum_out` 直接接回 `psum_in` 就得到累加器——反馈路径穿过 `always @(posedge clk)` 的寄存器，是合法电路，不是组合环。
3. **没有清零接口。** 唯一的清零路径是 `rst`。

### 2.2 必须先处理的 RTL 问题（M0）

| # | 问题 | 位置 | 后果 | 建议 |
|---|---|---|---|---|
| 1 | **乘法器被放大成 32×32** | [pe.sv:33-35](../rtl/pe.sv) | `a_ext`/`w_ext` 被扩展到 `ACC_BITS` 再相乘，`ACC_BITS=32` 时综合出**每个 PE 一个 32×32 有符号乘法器**（16 个 PE 就是 16 个），而输入实际只有 8 位 | 在 8×8 宽度内乘完再符号扩展，见下 |
| 2 | 端口声明为 `input reg` | [pe.sv:21-23](../rtl/pe.sv) | 作为内部单元无害；对外交付源码时不像 IP | 改 `input wire` |
| 3 | 无累加器清零接口 | [pe.sv:38-49](../rtl/pe.sv) | v1 只能用 `rst` 兼职（见 [10.2](#102-清累加器的权宜之计)） | Plan B 加 `acc_clr`/`acc_en`/`w_en` |
| 4 | 无有效位 / 无背压 | 全模块 | 无法知道哪一拍的 `psum_out` 有效 | v1 由序列器独占控制，不需要；Plan B 加 `in_valid` |
| 5 | 同步复位 | [pe.sv:38](../rtl/pe.sv) | PE 保持同步复位没问题，但顶层 `rst_n` 必须异步置位 + 同步释放 | 顶层加复位同步器 |

**问题 1 的修法**（数值等价，面积差一个数量级）：

```systemverilog
wire signed [A_BITS-1:0]        a_s  = a;          // 8 位
wire signed [W_BITS-1:0]        w_s  = w_inner;    // 8 位
wire signed [A_BITS+W_BITS-1:0] prod = a_s * w_s;  // 16 位积
// 符号扩展到 ACC_BITS 再累加
psum_out <= psum_s + {{(ACC_BITS-A_BITS-W_BITS){prod[A_BITS+W_BITS-1]}}, prod};
```

前提约束：`ACC_BITS >= A_BITS + W_BITS`。已在 [13.2](#132-编译期断言) 列为断言。

> 注：[pe_tb.sv](../tb/pe_tb.sv) 的参考模型 `e_mac` **已经是这个 8×8 形式**，所以 RTL 按上面收窄后 tb 无需改动即可通过。

### 2.3 从模块到 IP 的差距表

| 能力 | PE 现在 | v1 目标 | 落在哪个模块 |
|---|---|---|---|
| 计算 | ✅ | 保持 | `pe.sv` |
| 阵列化 | ❌ | ✅ | `pe_array.sv` |
| 数据供给 | ❌ | ✅ 三块片上 SRAM | `sram_dp.sv` |
| 时序控制 | ❌ | ✅ | `npu_seq.sv` |
| 软件可见性 | ❌ | ✅ AXI4-Lite + 寄存器 | `npu_regs.sv` |
| 完成通知 | ❌ | ✅ 电平中断 | `npu_regs.sv` |
| 错误可观测 | ❌ | ✅ ERROR / ABORTED 状态位 | `npu_regs.sv` |
| 版本识别 | ❌ | ✅ `ID` 寄存器 | `npu_regs.sv` |
| 复位方案 | ❌ | ✅ 异步置位同步释放 | `npu_top.sv` |

---

## 三、v1 范围与约束

明确写死，避免范围无限扩张。

| 项 | v1 定值 | 理由 |
|---|---|---|
| 阵列 | R×C = 4×4（参数化） | 16 个 PE，仿真规模和序列器复杂度都还可控 |
| 任务粒度 | **一次任务 = 一个 tile**，M ≤ R、N ≤ C、K 任意 | 不跨 tile 累加 ⇒ 不需要中途清累加器 |
| 大矩阵 | 驱动循环发多次任务 | 复杂度放在软件，硬件先简单 |
| 总线 | AXI4-Lite，32 位数据 / 32 位地址 / 单笔未完成 | 无流水、无 ID、无 burst |
| 时钟 | 单时钟域，ACLK = core clk | 多时钟域属于后面的事 |
| 数据入口 | 三块简单双口 SRAM（1W1R），**端口归属固定** | 见 [4.2](#42-为什么是三块-sram-而不是一块)，全设计无仲裁 |
| 中断 | 一根电平中断线 | MSI-X 属于 PCIe 阶段 |
| 精度 | A/W 8 位有符号；累加 32 位有符号；**无饱和** | 见 [9.4](#94-为什么-32-位累加器不会溢出) |

---

## 四、总体结构

### 4.1 框图

```
        CPU / 主机
             │  AXI4-Lite（只有从端，没有主端）
             ▼
   ┌─────────────────────────────────────────┐
   │ npu_regs.sv                             │
   │  · AXI4-Lite 从端（AW/W/B/AR/R 五通道）  │
   │  · 寄存器堆 + W1C / W1S 侧效             │
   │  · 中断聚合            ────────────────►│── irq（电平，高有效）
   │  · 三个窗口译码                          │
   └───────┬─────────────────────┬───────────┘
           │ start / cfg / status │ 窗口读写
           ▼                      ▼
   ┌───────────────┐      ┌──────────────────┐
   │ npu_seq.sv    │      │ ACT_SRAM (1W1R)  │  CPU 写 / 序列器读
   │  序列器 FSM    │◄────►│ W_SRAM   (1W1R)  │  CPU 写 / 序列器读
   │  地址生成      │      │ OUT_SRAM (1W1R)  │  序列器写 / CPU 读
   │  周期计数      │      └──────────────────┘
   └───────┬───────┘
           │ ldw / act_vec / w_vec
           ▼
   ┌───────────────┐
   │ pe_array.sv   │  R×C 广播阵列；psum_out → psum_in 自反馈构成累加器
   │  4×4 个 PE     │
   └───────────────┘
```

**注意这张图里没有的东西**：没有 AXI4 主端、没有 DMA、没有描述符、没有地址翻译。数据靠 CPU 通过窗口写进 SRAM。这是用带宽换简单——见 [14.5](#145-这个设计的性能量级)。

### 4.2 为什么是三块 SRAM 而不是一块

这是本设计里最省事的一个决定。每块 SRAM 的**读写端口归属是固定的**，于是全设计**没有任何仲裁逻辑**：

| SRAM | 写端口 | 读端口 | 字宽 | 深度 | 窗口 |
|---|---|---|---|---|---|
| `ACT_SRAM` | CPU（窗口写） | 序列器 | R×A_BITS = 32 | 1024 | `0x1000` |
| `W_SRAM` | CPU（窗口写） | 序列器 | C×W_BITS = 32 | 1024 | `0x2000` |
| `OUT_SRAM` | 序列器（drain） | CPU（窗口读） | ACC_BITS = 32 | R×C = 16 | `0x3000` |

如果只做一块 SRAM，CPU 写和序列器写会撞在同一个写端口上，就必须引入仲裁 + 反压 + AXI 顺序性问题。分三块把它们彻底解耦。

**`ACC_BITS` 从 16 改成 32 带来的一处简化**：`OUT_SRAM` 字宽原本打算"2 个累加器打包 = 32 位"，现在 **1 个累加器就是 32 位，正好等于 AXI4-Lite 数据宽度**，drain 每拍 1 个，`R×C` 也不再要求是偶数。

### 4.3 时钟与复位

- **单时钟域。** `s_axil_aclk` 与 core clk 是同一个时钟。不存在 CDC，因此不需要异步 FIFO 或握手同步器。
- **复位**：对外只有一根低有效 `rst_n`，**异步置位、同步释放**。内部用两级触发器同步释放：

```
rst_n ──┐
        │   ┌───┐  ┌───┐
        └──►│D Q├─►│D Q├──► rst_sync_n（内部使用）
     clk ──►└───┘  └───┘
           异步置位由 rst_n 直接作用在触发器上
```

- PE 内部仍是同步复位（[pe.sv:38](../rtl/pe.sv)），这也符合惯例：**同步复位逻辑 + 顶层异步置位/同步释放**。
- `SOFT_RESET`（寄存器）与 `rst_n` 的区别：`SOFT_RESET` 只复位 FSM 和状态位，**不清 SRAM、不清 `IRQ_STATUS`、不清配置寄存器**。`rst_n` 清一切。

---

## 五、AXI4-Lite 从端规格

### 5.1 端口

```systemverilog
// 全局
input  wire        aclk,          // = clk
input  wire        aresetn,       // 低有效，异步置位同步释放
// 写地址通道
input  wire [31:0] s_axil_awaddr,
input  wire [2:0]  s_axil_awprot, // 忽略
input  wire        s_axil_awvalid,
output wire        s_axil_awready,
// 写数据通道
input  wire [31:0] s_axil_wdata,
input  wire [3:0]  s_axil_wstrb,
input  wire        s_axil_wvalid,
output wire        s_axil_wready,
// 写响应通道
output wire [1:0]  s_axil_bresp,  // 2'b00=OKAY 2'b10=SLVERR 2'b11=DECERR
output wire        s_axil_bvalid,
input  wire        s_axil_bready,
// 读地址通道
input  wire [31:0] s_axil_araddr,
input  wire [2:0]  s_axil_arprot, // 忽略
input  wire        s_axil_arvalid,
output wire        s_axil_arready,
// 读数据通道
output wire [31:0] s_axil_rdata,
output wire [1:0]  s_axil_rresp,
output wire        s_axil_rvalid,
input  wire        s_axil_rready
```

`AWPROT` / `ARPROT` 按 AXI 规范必须存在，但本 IP **不使用**（不区分安全/特权/指令数据访问）。文档写明，避免集成者猜测。

### 5.2 传输规则

| 规则 | 定值 |
|---|---|
| 数据宽度 | 32 位，固定 |
| 地址宽度 | 32 位；**IP 只使用 `addr[13:0]`**，高位由互连 / BAR 译码负责 |
| 未完成事务 | **最多 1 笔**。`AWREADY`/`WREADY`/`ARREADY` 仅在空闲时拉高 |
| 写通道顺序 | `AW` 与 `W` 到达顺序任意，各自独立寄存；两者都到齐后执行写，再返回 `B` |
| 读延迟 | `AR` 握手后 1 拍 `RVALID`；不流水，`RVALID` 保持到 `RREADY` |
| 写数据交织 | 不支持（单笔未完成自然排除） |
| 非对齐访问 | **不支持**。寄存器与窗口都要求 32 位对齐 |
| `WSTRB` | 寄存器要求 `4'hF`；窗口也要求 `4'hF`（这样 SRAM 不需要字节使能） |
| 突发 | 不支持（AXI4-Lite 本身无 burst） |

> `WSTRB` 的限制和 L2 里记的约束是同一条：控制寄存器必须 32 位且对齐访问（[00-设备可编程模型.md](../../docs/L2-设备可编程模型/00-设备可编程模型.md) 的参考清单里 virtio 部分）。定成硬约束比"容忍非对齐"更容易验证。

### 5.3 响应码分配

| 情况 | 响应 |
|---|---|
| 寄存器区写且 `WSTRB != 4'hF` | **SLVERR** |
| 窗口写且 `WSTRB != 4'hF`，或地址非 4 字节对齐 | **SLVERR** |
| 窗口访问但偏移超出该 SRAM 实际深度 | **SLVERR** |
| 访问 `ACT`/`W` 窗口的**读** | OKAY，返回 0（只写区域） |
| 写 `OUT` 窗口 | OKAY，忽略（只读区域） |
| 寄存器区里未实现的偏移 | OKAY；**读返回 0，写被忽略** |
| 地址落在四个区域之外 | **DECERR** |

未实现偏移"读 0 写忽略"是刻意的：让驱动的 probe / 寄存器 dump 逻辑不用为空洞写特例。

---

## 六、地址映射

IP 内部视角（互连 / BAR 把这段映射到任意基址，IP 只认 `addr[13:0]`）：

| 偏移 | 大小 | 区域 | 说明 |
|---|---|---|---|
| `0x0000 – 0x0FFF` | 4 KB | 寄存器区 | 只实现 `0x000 – 0x02C` |
| `0x1000 – 0x1FFF` | 4 KB | `ACT` 窗口 | 只写；1024 个字，字 k 对应 A 的第 k 列 |
| `0x2000 – 0x2FFF` | 4 KB | `W` 窗口 | 只写；1024 个字，字 k 对应 W 的第 k 行 |
| `0x3000 – 0x3FFF` | 4 KB | `OUT` 窗口 | 只读；16 个字（R×C），字 idx 对应一个输出元素 |
| 其它 | — | — | **DECERR** |

整个 IP 占用 **16 KB** 地址空间。

---

## 七、寄存器规格

### 7.1 总表

偏移均为 IP 内相对地址。RO = 只读，RW = 读写，W1C = 写 1 清除，W1S = 写 1 自清。

| 偏移 | 名称 | 属性 | 复位值 | 一句话说明 |
|---|---|---|---|---|
| `0x000` | `ID` | RO | `0x4E50_0100` | 厂商 / 版本识别 |
| `0x004` | `CTRL` | RW / W1S | `0x0000_0000` | 启动、复位、中断门控、中止 |
| `0x008` | `STATUS` | RO | `0x0000_0000` | 忙 / 完成 / 错误（sticky） |
| `0x00C` | `IRQ_STATUS` | W1C | `0x0000_0000` | 未确认的中断事件 |
| `0x010` | `IRQ_MASK` | RW | `0x0000_0000` | 逐事件中断使能 |
| `0x014` | `CFG_M` | RW | `0x0000_0000` | 本次任务的 M（输出行数） |
| `0x018` | `CFG_N` | RW | `0x0000_0000` | 本次任务的 N（输出列数） |
| `0x01C` | `CFG_K` | RW | `0x0000_0000` | 本次任务的 K（累加深度） |
| `0x020` | `CYCLE_COUNT` | RO | `0x0000_0000` | 上一次任务的实际周期数 |
| `0x024` | `IRQ_COALESCE` | RW | `0x0000_0000` | **v1 保留**，读写可用但不生效 |
| `0x028` | `SCRATCH` | RW | `0x0000_0000` | 驱动 probe / 读回校验 |
| `0x02C – 0xFFC` | 保留 | — | — | 读 0，写忽略 |

### 7.2 `ID` (0x000, RO)

| 位 | 名称 | 值 |
|---|---|---|
| `[31:16]` | `MAGIC` | `0x4E50`（ASCII "NP"） |
| `[15:8]` | `MAJOR` | `0x01` |
| `[7:0]` | `MINOR` | `0x00` |

读回 `0x4E50_0100`。**驱动必须先读这个寄存器**：它是软件确认"我面对的是哪个版本的硬件"的唯一手段。寄存器布局一旦不兼容地改动，`MAJOR` 必须递增。

### 7.3 `CTRL` (0x004)

| 位 | 名称 | 属性 | 说明 |
|---|---|---|---|
| `[0]` | `START` | W1S | 写 1 启动一次任务。被 FSM 接收后自清；读回恒 0 |
| `[1]` | `SOFT_RESET` | W1S | 写 1 复位 FSM。自清 |
| `[2]` | `IRQ_EN` | RW | 全局中断使能（板级 / 全局开关） |
| `[3]` | `ABORT` | W1S | 写 1 中止当前任务。自清 |
| `[31:4]` | — | — | 保留，读 0 |

行为定义：

- **`START`**：锁存 `CFG_M/N/K` 到影子寄存器，清 `STATUS.DONE`，清 `CYCLE_COUNT`，FSM 从 `S_IDLE` 进入 `S_CHECK`。**不清 `IRQ_STATUS`**（理由见 [8.2](#82-为什么-statusdone-和-irq_statusdone-要分开)）。
- **`START` 在 `BUSY=1` 时**：**被忽略**，状态不变（v1 不做任务排队）。
- **`SOFT_RESET`**：FSM 立即回 `S_IDLE`；清 `STATUS`、清 `CYCLE_COUNT`、拉低累加器。**不清 SRAM、不清 `IRQ_STATUS`、不清 `CFG_*`、不清 `IRQ_MASK`。**
- **`ABORT`**：FSM 立即回 `S_IDLE`，置 `STATUS.ABORTED`，**不置 `DONE`**。

### 7.4 `STATUS` (0x008, RO)

| 位 | 名称 | 说明 | 清除方式 |
|---|---|---|---|
| `[0]` | `BUSY` | FSM 不在 `S_IDLE` | 硬件自动 |
| `[1]` | `DONE` | 上一次任务正常完成（sticky） | 下一次 `START` 或 `SOFT_RESET` |
| `[2]` | `ERROR` | 上一次任务配置非法（sticky） | 下一次 `START` 或 `SOFT_RESET` |
| `[3]` | `ABORTED` | 上一次任务被 `ABORT` 中止（sticky） | 下一次 `START` 或 `SOFT_RESET` |
| `[4]` | `OVF` | 累加器溢出（sticky）。**v1 恒为 0**，见 [9.4](#94-为什么-32-位累加器不会溢出) | 下一次 `START` 或 `SOFT_RESET` |
| `[31:5]` | — | 保留，读 0 | — |

`BUSY` 的定义是 `(state != S_IDLE)`；`DONE` 是 sticky 触发器，在**离开 `S_DONE` 的那一拍**（同一时钟沿回到 `S_IDLE`）被置位。两个信号在同一边沿更新，因此 `BUSY` 与 `DONE` **不会同时为 1**——这是一条应当在仿真里持续检查的断言。

### 7.5 `IRQ_STATUS` (0x00C, W1C) 与 `IRQ_MASK` (0x010)

两个寄存器位定义与 `STATUS[4:0]` 一致：`[0] DONE`、`[1] ERROR`、`[2] ABORTED`、`[3] OVF`。

- **`IRQ_STATUS`**：硬件置位，软件写 1 清除对应位（写 0 不动）。对应位清 0 后电平中断可能立即撤销。
- **`IRQ_MASK`**：位 = 1 表示该事件产生中断。复位值全 0，即**默认不产生中断**。

> `IRQ_MASK` 复位为 0 是刻意的：硬件复位后不会因为未知事件把 CPU 打进中断服务程序。软件必须显式使能。

### 7.6 `CFG_M` / `CFG_N` / `CFG_K` (0x014 / 0x018 / 0x01C)

| 位 | 名称 | 说明 |
|---|---|---|
| `[15:0]` | `M` / `N` / `K` | 本次任务的规模 |
| `[31:16]` | — | 保留，读 0 |

约束：`1 ≤ M ≤ R`、`1 ≤ N ≤ C`、`1 ≤ K ≤ 1024`。

- 复位值全 0 ⇒ **不配置就 `START` 会得到 `ERROR`**，这是刻意选择的"失败要响"行为，而不是静默算出一个 0。
- `START` 时被**锁存进影子寄存器**，任务运行期间软件改这三个寄存器**不影响正在执行的任务**（否则 FSM 的循环上界会在运行中变化）。

### 7.7 `CYCLE_COUNT` (0x020, RO)

上一次任务从 `START` 被接收到 `DONE` 之间的 `aclk` 周期数。`START` 时清零，任务运行期间持续递增。

用途：性能自测、验证序列器是否按预期拍数运行（见 [15](#十五验证计划)）。这个寄存器成本极低但排错价值很高——**L4 层的"性能计数器"就是从这种东西长出来的**。

### 7.8 `IRQ_COALESCE` (0x024, RW, v1 保留)

| 位 | 计划用途 |
|---|---|
| `[15:0]` | 事件聚合阈值（攒够 N 个事件再发中断） |
| `[31:16]` | 聚合时间（以 `aclk` 周期为单位） |

**v1 读写可用但不产生任何效果。** 保留它是为了让寄存器布局在加入该特性时不变。**驱动不得依赖此寄存器**——这条要写进驱动的注释里，否则会出现"驱动以为开了聚合，实际没开"的静默性能问题。

### 7.9 `SCRATCH` (0x028, RW)

无功能，纯粹用于驱动 probe 阶段的读写通路自检。这是 IP 里的标准做法：驱动加载时先写一个 pattern 再读回，能区分"设备没响应"和"寄存器写不进去"。

---

## 八、中断规格

### 8.1 中断逻辑

```systemverilog
assign irq = ctrl_irq_en & |(irq_status & irq_mask);
```

`irq` 是**电平、高有效**，保持到软件 W1C 清除（或清 `IRQ_EN` / 清 `IRQ_MASK`）。

### 8.2 为什么 `STATUS.DONE` 和 `IRQ_STATUS.DONE` 要分开

它们由同一个事件置位，但是**两个独立的触发器**，清除路径不同：

| | `STATUS.DONE` | `IRQ_STATUS.DONE` |
|---|---|---|
| 含义 | "上一次任务完成了" | "有一个未确认的中断" |
| 清除 | 下一次 `START`（或 `SOFT_RESET`） | 软件 W1C |
| 服务对象 | 轮询的驱动 | 中断驱动的驱动 |

这样做的好处是**两种驱动模型互不干扰**：用中断的驱动 W1C 之后 `STATUS.DONE` 仍然可读（便于事后诊断）；用轮询的驱动直接看 `STATUS.DONE`，不需要碰 `IRQ_STATUS`。

### 8.3 三条必须守住的语义

1. **事件置位不受 `IRQ_MASK` 影响。** `IRQ_STATUS` 由硬件**无条件**置位，`IRQ_MASK` 只决定要不要把 `irq` 拉高。这解决最常见的竞态：软件"先启动任务、后注册中断"不会丢事件。
   > 反例（错误做法）：把 mask 做成事件的门，mask=0 时事件直接丢弃。这样软件必须在启动前完成所有中断注册，且无法在运行中临时关中断再打开而不丢事件。
2. **清除只走 W1C。** 如果做成"读一下就清"，会和硬件的置位产生竞争；如果做成"电平自动清"，软件就没办法确认自己处理过了。
3. **`SOFT_RESET` 不碰 `IRQ_STATUS`。** 否则软件复位硬件时会把自己还没处理的中断吃掉。

### 8.4 为什么是电平而不是脉冲

脉冲中断有丢事件风险：如果 `irq` 只高一个周期，而 CPU 当时正在关中断或处理更高优先级的中断，这个事件就永久丢失了。电平中断 + sticky 状态位把"事件发生过"这件事记录下来，直到软件显式确认。

### 8.5 中断是可选的吗

**对这个 v1 的算力规模，中断的收益接近于零**——一次 4×4×K 的任务只有几十到几百拍，CPU 轮询 `STATUS.BUSY` 完全够用，而且延迟更低。

那为什么还要做？两个理由：

1. **学习价值。** 中断迫使你把"done / error / clear / 丢事件"这几个语义定对。这几个语义在后面的**命令队列 + doorbell + MSI-X** 阶段会原样复用，那里中断就不再是可选的。
2. **它是 L2 契约的一部分。** 一个只能轮询的设备在 L2 的"完成通知"那一节里是不完整的形态。

**收益真正出现的地方**在任务时长远超 CPU 处理开销、或者存在多队列/多上下文时——那是后续版本的事。

---

## 九、存储器与数据布局

### 9.1 字宽推导（本设计最容易算错的地方）

所有字宽都从参数派生：

| 量 | 表达式 | R=C=4, A=W=8, ACC=32 |
|---|---|---|
| `ACT_WORD_W` | `R × A_BITS` | 32 |
| `W_WORD_W` | `C × W_BITS` | 32 |
| `OUT_WORD_W` | `ACC_BITS` | 32 |
| `ACT_DEPTH` | 参数 | 1024 |
| `W_DEPTH` | 参数 | 1024 |
| `OUT_DEPTH` | `R × C` | 16 |

**关键约束**：`ACT_WORD_W`、`W_WORD_W`、`OUT_WORD_W` **都不得超过 32**（AXI4-Lite 数据宽度）。一旦超过，CPU 写一个 SRAM 字就需要多笔 AXI 事务，窗口映射和数据布局都要重新设计。所以：

- `R × A_BITS ≤ 32`
- `C × W_BITS ≤ 32`
- `ACC_BITS ≤ 32`

含义：**在当前 32 位总线宽度下，阵列维度受操作数位宽约束。** 例如 A_BITS=8 时 R ≤ 4；想做 8×8 阵列，要么把窗口改成 64 位、要么让 CPU 分两次写一个字（需要一个 staging 寄存器，见 [17](#十七已知限制与-plan-b)）。

### 9.2 数据布局（软件可见的契约）

第 k 步，序列器对每块 SRAM 各读一个字：

**`ACT` 窗口，字节偏移 `4*k`** — A 的第 k 列（沿 m 方向打包）：

| 位 | 内容 |
|---|---|
| `[7:0]` | `A[0][k]` |
| `[15:8]` | `A[1][k]` |
| `[23:16]` | `A[2][k]` |
| `[31:24]` | `A[3][k]` |

**`W` 窗口，字节偏移 `4*k`** — W 的第 k 行（沿 n 方向打包）：

| 位 | 内容 |
|---|---|
| `[7:0]` | `W[k][0]` |
| `[15:8]` | `W[k][1]` |
| `[23:16]` | `W[k][2]` |
| `[31:24]` | `W[k][3]` |

**`OUT` 窗口，字节偏移 `4*idx`，`idx = m*C + n`** — 一个有符号 32 位累加器：

| 位 | 内容 |
|---|---|
| `[31:0]` | `OUT[m][n]`，有符号 32 位，二进制补码 |

**语义**：

```
OUT[m][n] = Σ(k=0..K-1) A[m][k] × W[k][n]
```

A、W 是有符号 8 位，乘积有符号 16 位，累加有符号 32 位，**无饱和**（见 [9.4](#94-为什么-32-位累加器不会溢出)）。

### 9.3 数值例子（写 testbench 时直接用这个）

参数：R=4、C=4、K=2、A_BITS=W_BITS=8、ACC_BITS=32。

输入：

```
A = [[1, 2],        W = [[1, 0, 0, 0],
     [3, 4],             [0, 1, 0, 0]]
     [5, 6],
     [7, 8]]
```

写入窗口的字：

| 地址 | 值 | 组成 |
|---|---|---|
| `0x1000` | `0x07050301` | `{A[3][0], A[2][0], A[1][0], A[0][0]}` = {7,5,3,1} |
| `0x1004` | `0x08060402` | `{A[3][1], A[2][1], A[1][1], A[0][1]}` = {8,6,4,2} |
| `0x2000` | `0x00000001` | `{W[0][3..0]}` = {0,0,0,1} |
| `0x2004` | `0x00000100` | `{W[1][3..0]}` = {0,0,1,0} |

配置：`CFG_M=4`、`CFG_N=4`、`CFG_K=2`，然后 `CTRL.START=1`。

期望输出（`OUT[m][n] = Σ_k A[m][k]·W[k][n]`）：

| idx | `m*C+n` | 值 | | idx | `m*C+n` | 值 |
|---|---|---|---|---|---|---|
| 0 | `OUT[0][0]` | 1 | | 8 | `OUT[2][0]` | 5 |
| 1 | `OUT[0][1]` | 2 | | 9 | `OUT[2][1]` | 6 |
| 2 | `OUT[0][2]` | 0 | | 10 | `OUT[2][2]` | 0 |
| 3 | `OUT[0][3]` | 0 | | 11 | `OUT[2][3]` | 0 |
| 4 | `OUT[1][0]` | 3 | | 12 | `OUT[3][0]` | 7 |
| 5 | `OUT[1][1]` | 4 | | 13 | `OUT[3][1]` | 8 |
| 6 | `OUT[1][2]` | 0 | | 14 | `OUT[3][2]` | 0 |
| 7 | `OUT[1][3]` | 0 | | 15 | `OUT[3][3]` | 0 |

即 `OUT` 窗口 `0x3000 + 4*idx` 依次读到 `1, 2, 0, 0, 3, 4, 0, 0, 5, 6, 0, 0, 7, 8, 0, 0`。

> **自检模式**：令 `A = 单位矩阵`，则 `OUT == W`（取前 C 列）。这一条能同时覆盖窗口写入、地址生成、LDW/MAC 时序、drain 顺序和读回路径，是最划算的端到端测试。

### 9.4 为什么 32 位累加器不会溢出

`ACC_BITS` 从 16 改成 32 之后，溢出从"需要小心"变成了"可以证明不会发生"。推导：

- 8 位有符号操作数的绝对值上界：`|a| ≤ 128`，`|w| ≤ 128`
- 单项积的界：`|a·w| ≤ 2^14 = 16384`
- K 项和的界：`|Σ| ≤ K × 2^14`
- 有符号 32 位可表示到 `2^31 - 1`

**发生溢出需要 `K × 2^14 ≥ 2^31`，即 `K ≥ 2^17 = 131072`。**

而 `ACT_DEPTH = W_DEPTH = 1024`，`K ≤ 1024 = 2^10`，此时 `|Σ| ≤ 2^24`，**离 32 位上限还有 7 位余量**。

一般式：所需位宽 `= 1 + (A_BITS - 1) + (W_BITS - 1) + ceil(log2 K)`，K=1024、A=W=8 时 = 25 位。

**结论与后果**：

1. v1 的 `STATUS.OVF` **恒为 0**，是"不可能发生"而不是"没实现"。文档这样写才诚实。
2. 一旦把 `ACT_DEPTH` 加大到 128K 以上、或者把操作数加宽到 16 位（`A_BITS=W_BITS=16` 时 K 只需 `2^3` 就可溢出 32 位），`OVF` 就变成必须实现的特性。
3. 这个推导必须在**改 `ACT_DEPTH` 或 `A_BITS`/`W_BITS` 时重新算一遍**，并同步更新本文档。

---

## 十、序列器

### 10.1 状态机

```
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              │
   ┌─────────┐  START   ┌─────────┐  非法   ┌─────────┐ │
   │ S_IDLE  │─────────►│ S_CHECK │────────►│ S_ERROR │─┘
   └─────────┘          └────┬────┘         └─────────┘
                             │ 合法
                             ▼
                       ┌───────────┐
                       │ S_ACC_CLR │  1 拍：清零累加器 + 预取 w[0]
                       └─────┬─────┘
                             ▼
                  ┌──────────────────────┐
             ┌───►│ S_LD_W(k)   共 K 拍   │  装载 w[k]，发 a_addr=k、w_addr=k+1
             │    └──────────┬───────────┘
             │               ▼
             │    ┌──────────────────────┐
             └────│ S_MAC(k)    共 K 拍   │  累加 a[k]（已就绪）
        k<K-1     └──────────┬───────────┘
                             │ k==K-1
                             ▼
                       ┌───────────┐
                       │ S_DRAIN   │  R×C 拍：每拍写 1 个累加器到 OUT_SRAM
                       └─────┬─────┘
                             ▼
                       ┌───────────┐
                       │ S_DONE    │  1 拍：置 STATUS.DONE + IRQ_STATUS.DONE
                       └─────┬─────┘
                             └──────────► S_IDLE
```

拍数预算：`3 + 2K + R×C`（`S_CHECK` 1 + `S_ACC_CLR` 1 + `S_LD_W` K + `S_MAC` K + `S_DRAIN` R×C + `S_DONE` 1）。4×4、K=4 时 ≈ 27 拍。

> `CYCLE_COUNT` 的**精确值**取决于 `START` 在哪一拍被 FSM 接收（软件写下 `START` 之后，FSM 可能晚一拍才看到），所以验证时检查**范围**（例如 `25 ≤ count ≤ 29`）而不是精确等值——否则会得到一个和实现细节死绑的脆弱测试。

| 状态 | 拍数 | 输出 |
|---|---|---|
| `S_IDLE` | — | `busy=0`；等 `start` |
| `S_CHECK` | 1 | 校验 M/N/K；非法 → `S_ERROR` |
| `S_ERROR` | 1 | 置 `STATUS.ERROR` + `IRQ_STATUS.ERROR`；回 `S_IDLE` |
| `S_ACC_CLR` | 1 | `acc_clr=1`；**`w_raddr=0`**（预取第 0 个权重） |
| `S_LD_W(k)` | K | `ldw=1`；`w` 取上一拍预取的 `w_rdata`；发 `w_raddr=k+1`（若 `k+1<K`）和 `a_raddr=k` |
| `S_MAC(k)` | K | `ldw=0`；`act_vec = a_rdata`（已就绪） |
| `S_DRAIN` | R×C | `out_we=1`；`out_waddr=i`；`out_wdata = acc_out[i*ACC_BITS +: ACC_BITS]` |
| `S_DONE` | 1 | 置 `DONE`；回 `S_IDLE` |

`ABORT` 可以从任意状态直接跳回 `S_IDLE` 并置 `ABORTED`。

### 10.2 清累加器的权宜之计

PE 没有清零接口，唯一的清零路径是 `rst`（[pe.sv:38-49](../rtl/pe.sv)）。v1 的做法是在阵列层：

```systemverilog
// pe_array.sv 内部
assign pe_rst = rst | acc_clr;
```

`rst` 同时会清掉 `w_inner`，但**这无害**——因为 k=0 的 `S_LD_W` 会立刻重新装载权重。

这是"不改 `pe.sv`"要付的代价：语义上有点脏（`rst` 被当成"清累加器"用），但它让 v1 完全不碰已通过自检的 PE。Plan B 加上 `acc_clr` 端口后这条就删掉。

### 10.3 SRAM 读延迟与预取

序列器的地址生成是这一步最容易写错的地方。三块 SRAM 都是**同步读、1 拍延迟**，所以：

- `S_MAC(k)` 需要 `a_rdata = A[k]` ⇒ 地址 `k` 必须在 `S_LD_W(k)` 发出
- `S_LD_W(k)` 需要 `w_rdata = W[k]` 来装权重 ⇒ 该地址必须**更早一拍**发出

于是：

| 拍 | 发出的 `w_raddr` | 发出的 `a_raddr` | 本拍用到的 `w_rdata` | 本拍用到的 `a_rdata` |
|---|---|---|---|---|
| `S_ACC_CLR` | 0 | — | — | — |
| `S_LD_W(0)` | 1 | 0 | `W[0]` ✅ | — |
| `S_MAC(0)` | 2 | 1 | — | `A[0]` ✅ |
| `S_LD_W(1)` | 3 | 1 | `W[1]` ✅ | — |
| `S_MAC(1)` | 4 | 2 | — | `A[1]` ✅ |

`S_ACC_CLR` 存在的意义之一就是**把 `w` 的预取流水填满**，让 `S_LD_W(0)` 一进状态就有数据。

> **v1 的简化选项**：如果为了先跑通把 SRAM 写成组合读（`assign rdata = mem[addr]`），上面这套预取逻辑全部不需要，序列器会简单很多。**但这必须在代码注释里标明是 v1 简化**——换成真实 SRAM macro 时这里必须重做。这不是"以后再说"的优化，而是接口语义的实质变化。

### 10.4 累加器反馈

```
pe_array 内部：
    pe[r][c].psum_in = pe[r][c].psum_out      // 直接连，不加寄存器
    pe[r][c].load    = ldw
    pe[r][c].a       = act_vec[r*A_BITS +: A_BITS]
    pe[r][c].w       = w_vec[c*W_BITS +: W_BITS]
    pe[r][c].rst     = rst | acc_clr
```

`psum_out` 直接接回 `psum_in` 是**合法**的：反馈路径穿过 PE 内部的 `always @(posedge clk)` 寄存器，不构成组合环。等价于 `psum_out <= psum_out + a*w_inner`，正是累加器。

> 需要解释一处看似矛盾的地方：`pe.sv` 的注释（[pe.sv:11-12](../rtl/pe.sv)）写着"不要把本模块自己的 `psum_out` 绕回来当 `psum_in`"。那条禁令是**针对单元测试的契约**说的——单元测试里 `psum_in` 完全由外部向量提供，期望值才有唯一确定的含义。在阵列层做反馈是设计意图，两者不冲突。

---

## 十一、模块端口清单

### 11.1 `sram_dp` — 通用简单双口 SRAM（1W1R）

```systemverilog
module sram_dp #(
    parameter  int DW    = 32,
    parameter  int DEPTH = 1024,
    localparam int AW    = $clog2(DEPTH)   // 派生量必须在参数表内，端口列表才能引用
) (
    input  wire                    clk,
    // 写端口（同步写）
    input  wire                    we,
    input  wire [AW-1:0]           waddr,
    input  wire [DW-1:0]           wdata,
    // 读端口（同步读，1 拍延迟）
    input  wire                    re,
    input  wire [AW-1:0]           raddr,
    output logic [DW-1:0]          rdata
);
```

v1 用行为级寄存器数组实现，接口与真实 SRAM macro 保持一致（同步读、1 拍延迟），以便将来直接替换。**无字节使能**——这是 [5.2](#52-传输规则) 要求 `WSTRB == 4'hF` 的直接后果。

### 11.2 `pe_array` — 广播式 MAC 阵列

```systemverilog
module pe_array #(
    parameter int R = 4, C = 4,
    parameter int A_BITS = 8, W_BITS = 8, ACC_BITS = 32
) (
    input  wire                    clk,
    input  wire                    rst,        // 全局复位（同步）
    input  wire                    acc_clr,    // 1 拍清零累加器 → pe.rst = rst|acc_clr
    input  wire                    ldw,        // → pe.load
    input  wire [R*A_BITS-1:0]     act_vec,    // bit[r*A_BITS +: A_BITS] → PE(r,·)
    input  wire [C*W_BITS-1:0]     w_vec,      // bit[c*W_BITS +: W_BITS] → PE(·,c)
    output wire [R*C*ACC_BITS-1:0] acc_out     // bit[(r*C+c)*ACC_BITS +: ACC_BITS]
);
```

`acc_out` 在 R=C=4、ACC_BITS=32 时是 **512 位**。这是阵列的天然输出宽度，drain 时按 `ACC_BITS` 逐个切片写入 `OUT_SRAM`。

### 11.3 `npu_seq` — 序列器

```systemverilog
module npu_seq #(
    parameter  int R = 4, C = 4,
    parameter  int A_BITS = 8, W_BITS = 8, ACC_BITS = 32,
    parameter  int ACT_DEPTH = 1024, W_DEPTH = 1024,
    localparam int AW_ACT = $clog2(ACT_DEPTH),
    localparam int AW_W   = $clog2(W_DEPTH),
    localparam int AW_OUT = $clog2(R*C)
) (
    input  wire                    clk,
    input  wire                    rst,
    // 控制
    input  wire                    start,
    input  wire                    soft_reset,
    input  wire                    abort,
    input  wire [15:0]             cfg_m, cfg_n, cfg_k,
    // ACT_SRAM 读口
    output wire [AW_ACT-1:0]       act_raddr,
    input  wire [R*A_BITS-1:0]     act_rdata,
    // W_SRAM 读口
    output wire [AW_W-1:0]         w_raddr,
    input  wire [C*W_BITS-1:0]     w_rdata,
    // OUT_SRAM 写口
    output wire                    out_we,
    output wire [AW_OUT-1:0]       out_waddr,
    output wire [ACC_BITS-1:0]     out_wdata,
    // 阵列
    output wire                    ldw,
    output wire                    acc_clr,
    output wire [R*A_BITS-1:0]     act_vec,
    output wire [C*W_BITS-1:0]     w_vec,
    input  wire [R*C*ACC_BITS-1:0] acc_out,
    // 状态
    output wire                    busy,
    output wire                    done_pulse,
    output wire                    error_pulse,
    output wire                    aborted_pulse,
    output wire [31:0]             cycle_count
);
```

### 11.4 `npu_regs` — AXI4-Lite 从端 + 寄存器 + 中断

```systemverilog
module npu_regs #(...) (
    input  wire        clk, rst_n,
    // ---- AXI4-Lite（见 5.1 节的完整端口）----
    ...
    // ---- 控制/状态 ----
    output wire        start,
    output wire        soft_reset,
    output wire        abort,
    output wire        irq_en,
    output wire [15:0] cfg_m, cfg_n, cfg_k,
    input  wire        busy,
    input  wire        done_pulse,
    input  wire        error_pulse,
    input  wire        aborted_pulse,
    input  wire [31:0] cycle_count,
    // ---- 中断 ----
    output wire        irq,
    // ---- SRAM 窗口 ----
    output wire                   act_we,
    output wire [AW_ACT-1:0]      act_waddr,
    output wire [R*A_BITS-1:0]    act_wdata,
    output wire                   w_we,
    output wire [AW_W-1:0]        w_waddr,
    output wire [C*W_BITS-1:0]    w_wdata,
    output wire [AW_OUT-1:0]      out_raddr,
    input  wire [ACC_BITS-1:0]    out_rdata
);
```

### 11.5 `npu_top` — 集成与复位同步

```systemverilog
module npu_top #(
    parameter int R = 4, C = 4,
    parameter int A_BITS = 8, W_BITS = 8, ACC_BITS = 32,
    parameter int ACT_DEPTH = 1024, W_DEPTH = 1024
) (
    input  wire        clk,
    input  wire        rst_n,        // 异步置位，内部同步释放
    // AXI4-Lite 从端（见 5.1）
    ...
    output wire        irq
);
```

`npu_top` 的职责只有三件：复位同步、把 `npu_regs` 的窗口端口接到三块 SRAM、把 `npu_seq` 和 `pe_array` 连起来。**不含任何逻辑决策。**

---

## 十二、错误处理

| 情况 | 检测点 | 行为 |
|---|---|---|
| `M=0` 或 `M>R` | `S_CHECK` | `STATUS.ERROR` + `IRQ_STATUS.ERROR`，回 `S_IDLE`；累加器不动，SRAM 不动 |
| `N=0` 或 `N>C` | `S_CHECK` | 同上 |
| `K=0` 或 `K>ACT_DEPTH` | `S_CHECK` | 同上 |
| `START` 时 `BUSY=1` | `npu_regs` | **忽略**，状态不变（v1 不排队） |
| 任务中途改 `CFG_*` | 影子寄存器 | 不影响当前任务 |
| `ABORT` | `npu_seq` | 立即回 `S_IDLE`，置 `ABORTED`，**不置 `DONE`** |
| 写入只读寄存器 / 读只写窗口 | 地址译码 | 按 [5.3](#53-响应码分配)：忽略或返回 0，OKAY |
| 非对齐或 `WSTRB!=4'hF` | 地址译码 | **SLVERR** |
| 访问四个区域之外 | 地址译码 | **DECERR** |
| 累加器溢出 | — | **v1 不会发生**，见 [9.4](#94-为什么-32-位累加器不会溢出) |

**设计取向：失败要响，不要静默。** 所以 `CFG_*` 复位值为 0 而不是"默认全规模"，不配置就 `START` 会明确报 `ERROR`。同理，`ERROR` 是 sticky 的，软件不主动清就一直可见。

---

## 十三、参数与派生约束

### 13.1 参数表

| 参数 | 默认 | 含义 | 约束 |
|---|---|---|---|
| `R` | 4 | 阵列行数（= 输出行块大小） | `R×A_BITS ≤ 32` |
| `C` | 4 | 阵列列数（= 输出列块大小） | `C×W_BITS ≤ 32` |
| `A_BITS` | 8 | 激活位宽 | `≥2` |
| `W_BITS` | 8 | 权重位宽 | `≥2` |
| `ACC_BITS` | 32 | 累加位宽 | `≤32` 且 `≥ A_BITS+W_BITS` |
| `ACT_DEPTH` | 1024 | ACT_SRAM 深度（字数） | `K ≤ ACT_DEPTH` |
| `W_DEPTH` | 1024 | W_SRAM 深度（字数） | 应等于 `ACT_DEPTH` |

### 13.2 编译期断言

建议在 `npu_top` 里用 elaboration 期断言把约束固化下来，而不是靠文档提醒：

| 断言 | 理由 |
|---|---|
| `R*A_BITS <= 32` | 否则 ACT 字宽超 AXI 数据宽度 |
| `C*W_BITS <= 32` | 否则 W 字宽超 AXI 数据宽度 |
| `ACC_BITS <= 32` | 否则 OUT 字宽超 AXI 数据宽度 |
| `ACC_BITS >= A_BITS+W_BITS` | 否则符号扩展移位量为负（见 [2.2](#22-必须先处理的-rtl-问题m0)） |
| `W_DEPTH == ACT_DEPTH` | K 只有一个配置寄存器 |
| `R >= 1 && C >= 1` | 退化配置 |

这些断言在真实 IP 里是标准做法：**把集成约束变成工具报错，而不是集成者踩坑后回来翻文档。**

---

## 十四、软件编程模型

### 14.1 驱动流程

```c
/* 1. 识别硬件 */
u32 id = readl(base + 0x000);            /* 必须 == 0x4E500100 */
if ((id >> 16) != 0x4E50)      return -ENODEV;
if (((id >> 8) & 0xFF) != 1)   return -EINVAL;  /* MAJOR 不匹配：寄存器布局不同 */

/* 2. 配置规模 */
writel(M, base + 0x014);
writel(N, base + 0x018);
writel(K, base + 0x01C);

/* 3. 填数据（ACT 窗口，字 k = A 的第 k 列） */
for (k = 0; k < K; k++)
    writel(act_word[k], base + 0x1000 + 4 * k);
/* W 窗口，字 k = W 的第 k 行 */
for (k = 0; k < K; k++)
    writel(w_word[k],   base + 0x2000 + 4 * k);

/* 4. 使能中断（可选） */
writel(IRQ_DONE, base + 0x010);          /* IRQ_MASK */
writel(CTRL_IRQ_EN, base + 0x004);

/* 5. 启动 */
writel(CTRL_START, base + 0x004);

/* 6a. 轮询式驱动 */
while (!(readl(base + 0x008) & STATUS_DONE)) {
    if (readl(base + 0x008) & STATUS_ERROR) return -EIO;
}

/* 6b. 中断式驱动（ISR 里） */
u32 ev = readl(base + 0x00C);            /* IRQ_STATUS */
if (ev & IRQ_DONE) {
    writel(IRQ_DONE, base + 0x00C);      /* W1C：写 1 清除 */
    complete(&done);
}

/* 7. 读结果：OUT 窗口，idx = m*C + n */
for (idx = 0; idx < M * N; idx++)
    out[idx] = (s32)readl(base + 0x3000 + 4 * idx);
```

### 14.2 写序的正确性

第 2、3 步的写必须在第 5 步的 `START` **之前真正到达设备**。

- 在 **AXI4-Lite** 上这是自动成立的：每笔写都有 `B` 响应，规范的 master 会等 `B` 才发下一笔。`npu_regs` 每笔写都返回 `B`，所以顺序天然正确。
- 在 **PCIe** 上这**不成立**：MMIO 写是 posted write，`START` 可能先于配置写到达设备。这时需要"读回一个寄存器来冲刷未完成的写"，或者把配置和启动合成一笔写。L2 里已经记下这条（[00-设备可编程模型.md](../../docs/L2-设备可编程模型/00-设备可编程模型.md) 的参考清单：posted write 与 read-back 冲刷）。

**这条差异必须在文档里写明**，否则将来从 AXI 仿真环境切到 PCIe 真卡时会出现"大部分时候对、偶尔算错"的诡异 bug。

### 14.3 为什么 `START` 不放在 `CTRL` 的同一个字里合并配置

已经分开：`CFG_*` 和 `CTRL` 是不同偏移。这样 `START` 只表达"开始"，不隐含"顺带改配置"，减少了软件误用的可能。

### 14.4 中断式 vs 轮询式

| | 轮询 | 中断 |
|---|---|---|
| 延迟 | 最低（无中断入口/返回开销） | 有固定开销 |
| CPU 占用 | 空转占满一个核 | 只在事件时占用 |
| 适用 | 短任务、低延迟推理 | 长任务、多队列、CPU 要干别的 |

v1 两者都支持（见 [8.2](#82-为什么-statusdone-和-irq_statusdone-要分开)）。**但要注意**：对 4×4×K 这种几十拍的任务，轮询更快。这不是缺陷，是规模决定的——中断的收益要等任务时长上来才出现。

### 14.5 这个设计的性能量级

必须诚实说明，避免误判：

- 一次 4×4×K 任务：约 `3 + 2K + 16` 拍。K=4 时约 **27 拍**。
- 计算量：`4×4×4 = 64 MAC`。16 个 PE 理想情况 4 拍就算完，实际 27 拍 ⇒ **平均每拍 2.4 个 MAC，PE 利用率约 15%**。
- 利用率低的两个原因：`LDW` 与 `MAC` 分离（每步 2 拍，直接砍半）、固定开销占 19 拍（`S_CHECK` 1 + `S_ACC_CLR` 1 + `S_DRAIN` 16 + `S_DONE` 1）。

更重要的瓶颈**不在计算**：数据是 CPU 用 `writel` 一个字一个字写进 SRAM 的。K=1024 时需要写 2048 个字（ACT 1024 + W 1024），而计算只要约 2067 拍。若每笔 AXI4-Lite 写占 2~3 拍，**光写数据就要 4000~6000 拍——比计算还慢**。这正是 README 里说的"数据移动税"。

所以 v1 的定位是**功能闭环**，不是性能。真正的性能版本需要 DMA（见 [17](#十七已知限制与-plan-b)）。

---

## 十五、验证计划

### 15.1 分层

| 层 | 文件 | 内容 |
|---|---|---|
| PE 单元 | [pe_tb.sv](../tb/pe_tb.sv) | 已有，34 条向量，含 32 位累加链与边界覆盖。**保持不动**，作为回归 |
| 总线 BFM | `tb/axil_bfm.sv` | `write32(addr,data)` / `read32(addr)->data` 任务，替代真驱动 |
| 寄存器层 | `tb/npu_regs_tb.sv` | 寄存器语义（见 15.2） |
| 端到端 | `tb/npu_top_tb.sv` | 完整任务（见 15.3） |

### 15.2 寄存器层测试项

| # | 测试 | 期望 |
|---|---|---|
| 1 | 读 `ID` | `0x4E50_0100` |
| 2 | `SCRATCH` 写 pattern 读回 | 相等（含 `0xFFFFFFFF`、`0x00000000`、`0xA5A5A5A5`） |
| 3 | 写 RO 寄存器（`ID`/`STATUS`） | 被忽略，读回不变 |
| 4 | 读未实现偏移 | 0，resp = OKAY |
| 5 | 写未实现偏移 | 无副作用，resp = OKAY |
| 6 | `IRQ_STATUS` W1C | 只清写 1 的位，其余位保持 |
| 7 | **mask 时序（防丢事件）** | 置位事件时 `IRQ_MASK=0` ⇒ `irq=0`；之后写 `IRQ_MASK` 使能 ⇒ **`irq` 必须拉高** |
| 8 | `IRQ_EN=0` | `irq=0`，但 `IRQ_STATUS` 仍置位 |
| 9 | `WSTRB != 4'hF` 的寄存器写 | resp = **SLVERR** |
| 10 | 非对齐地址 | resp = **SLVERR** |
| 11 | 区域外地址 | resp = **DECERR** |
| 12 | `ACT`/`W` 窗口读 | 0，OKAY |
| 13 | `OUT` 窗口写 | 无副作用，OKAY |
| 14 | 窗口超出深度 | **SLVERR** |
| 15 | `START` 时 `BUSY=1` | 被忽略，配置与状态不变 |

第 7 项是**整个寄存器层最重要的一条**：它验证的是"事件不会因为当时没使能而丢失"这个语义。这条测不过，中断驱动的驱动就会有难以复现的挂死。

### 15.3 端到端测试项

| # | 测试 | 期望 |
|---|---|---|
| 1 | **A = 单位矩阵** | `OUT == W`（前 C 列） |
| 2 | [9.3](#93-数值例子写-testbench-时直接用这个) 的数值例子 | 逐字匹配 |
| 3 | 含负权重、负激活 | 与参考模型逐字匹配 |
| 4 | K = 1 / K = 4 / K = 1024 | 都正确；`CYCLE_COUNT` 落在 `3+2K+16` 附近的范围内（不要写精确等值，理由见 [10.1](#101-状态机)） |
| 5 | `K = 0` / `M = 0` / `K > 1024` | `STATUS.ERROR` + `IRQ_STATUS.ERROR` |
| 6 | `ABORT` 在 `S_MAC` 中途 | 回 `S_IDLE`；`ABORTED=1`；`DONE=0` |
| 7 | 连续两次任务 | `done → start → done`，第二次结果独立正确 |
| 8 | `SOFT_RESET` 在忙时 | FSM 回 `S_IDLE`，`BUSY=0`；`IRQ_STATUS` 不变 |
| 9 | 中断路径 | `DONE` 事件拉高 `irq`；W1C 后拉低 |

### 15.4 断言

| 断言 | 理由 |
|---|---|
| `BUSY` 与 `DONE` 不同时为 1 | 状态机互斥性 |
| `irq == 0` 时 `(irq_status & irq_mask) == 0` | 中断不会凭空产生 |
| `irq_status` 只在事件拍被置位，不被读操作清除 | W1C 语义 |
| `npu_seq` 状态是独热 / 合法编码 | 状态机安全 |
| `out_we` 时 `out_waddr < R*C` | drain 不越界 |
| `act_raddr < ACT_DEPTH`、`w_raddr < W_DEPTH` | 预取逻辑不越界 |

### 15.5 仿真命令

```bash
cd mini_npu/sim
make            # iverilog -g2012 -Wall 编译，vvp 运行
gtkwave pe.vcd  # 看波形
```

环境与构建细节（工具链、cygwin 的 PATH 坑、Makefile 依赖）见 [sim/README.md](../sim/README.md)。

---

## 十六、里程碑

每个里程碑都要求"可验证"，不留"差不多完成了"。

| # | 交付 | 验证方式 | 依赖 |
|---|---|---|---|
| **M0** | 修 [2.2](#22-必须先处理的-rtl-问题m0) 的问题 1、2 | [pe_tb.sv](../tb/pe_tb.sv) 34 条向量全过（tb 无需改动） | — |
| **M1** | `sram_dp` + AXI4-Lite 从端 + `ID`/`SCRATCH` | tb 读回 `0x4E500100`；`SCRATCH` 写读；SLVERR/DECERR 路径 | M0 |
| **M2** | 三个窗口 | tb 从 ACT/W 窗口写入、从 OUT 窗口读出 | M1 |
| **M3** | `pe_array` + `npu_seq`，`STATUS.DONE` 可轮询 | A = 单位矩阵通过；[9.3](#93-数值例子写-testbench-时直接用这个) 例子逐字匹配 | M2 |
| **M4** | `IRQ_STATUS`/`IRQ_MASK`/`IRQ_EN` + `irq` | [15.2](#152-寄存器层测试项) 第 7、8 项 | M3 |
| **M5** | `CYCLE_COUNT` + ERROR 路径 + `ABORT` | [15.3](#153-端到端测试项) 第 5、6 项；周期数符合预算 | M4 |
| **M6** | **Plan B**：`pe.sv` 加 `w_en`/`acc_en`/`acc_clr`/`in_valid`；序列器 1 拍/k；跨 tile 累加 | `pe_tb` 需同步改造（唯一要动 `pe.sv` 的里程碑） | M5 |

**M6 的收益**：吞吐 ×2、去掉"用 `rst` 当清零"的脏做法、支持 M>R 的分块累加、为流水/背压留位置。

**关键性质**：M6 改的全是数据面，**v1 定下的寄存器布局、地址映射、FSM 状态划分一条都不用改**。这就是先定契约、后扩数据面的价值。

---

## 十七、已知限制与 Plan B

### 17.1 v1 有意不做的事

| # | 限制 | 影响 | 什么时候必须解决 |
|---|---|---|---|
| 1 | **无 DMA**，数据靠 CPU 逐字写 | 数据搬运开销 ≈ 计算开销（见 [14.5](#145-这个设计的性能量级)） | 想让算力真正发挥作用时 |
| 2 | **一次任务一个 tile**（M≤R、N≤C） | 大矩阵要靠驱动循环 | 想减少 launch 开销时 |
| 3 | **每步 2 拍**（LDW/MAC 分离） | 吞吐减半 | 想提性能时 → Plan B |
| 4 | **无流水**，序列器串行推进 | 延迟 = 拍数总和 | 同上 |
| 5 | **无背压**（无 valid/ready） | 序列器独占控制，外部无法插队 | 引入 DMA 时**必须**加 |
| 6 | **单时钟域** | 无法接不同频率的总线时钟 | 集成到真实 SoC 时常见 |
| 7 | **`OVF` 不实现** | 当前参数下不会溢出（[9.4](#94-为什么-32-位累加器不会溢出)） | 加大 `ACT_DEPTH` 或操作数位宽时 |
| 8 | **`IRQ_COALESCE` 不实现** | 中断无法聚合 | 高吞吐场景 |
| 9 | **无 MSI-X**，只有一根电平线 | 多队列无法绑不同 CPU 核 | PCIe 阶段 |
| 10 | **无命令队列 / doorbell** | 每次任务都要 CPU 写寄存器 | 想把 CPU 从提交路径上摘掉时 |
| 11 | **R×A_BITS ≤ 32 的约束** | 8 位操作数下阵列最大 4 行 | 想做 8×8 阵列时 → 见下 |

### 17.2 第 11 条的具体解法

如果将来要做 8×8 阵列且操作数 8 位，`R×A_BITS = 64 > 32`，CPU 写一个 ACT 字需要两笔 AXI 事务。三种做法：

1. **窗口加宽**：SRAM 保持 64 位，`npu_regs` 加一个 staging 寄存器，CPU 写低半字、再写高半字，第二笔触发 SRAM 写。代价：软件要成对写，且中间不能被中断打断（或用两笔写 + 一个 `COMMIT` 寄存器）。
2. **多拍窄读**：序列器分两拍读一个 ACT 字，序列器变复杂。
3. **改总线宽度**：接 AXI4（非 Lite）并把数据宽度提到 64/128。这也顺便解决了带宽问题，但工作量最大。

**推荐第 1 种**（staging 寄存器）：对软件是"写两个字"，对序列器完全透明——序列器的地址生成逻辑一行都不用改。

### 17.3 Plan B 的具体内容

| 改动 | 位置 | 收益 |
|---|---|---|
| 加 `w_en` / `acc_en`（取代互斥的 `load`） | `pe.sv` | 权重装载与累加解耦，序列器可 1 拍/k |
| 加 `acc_clr` | `pe.sv` | 去掉"用 `rst` 当清零" |
| 加 `in_valid`（或 `acc_en` 兼作） | `pe.sv` | 无有效拍不污染累加器 |
| 加 `w_en` 预取流水 | `npu_seq.sv` | 权重总线提前一拍 |
| 加 tile 循环（M/R × N/C） | `npu_seq.sv` | 支持大矩阵一次 launch |
| 加 DMA 主端 | 新模块 | 数据搬运不再占 CPU |

**顺序建议**：前三项（改 `pe.sv`）是纯数据面收益，成本低、风险可控，做完再做 DMA。DMA 会引入背压、地址翻译（IOMMU/PASID）、一致性问题——那是 L3 的内容，属于另一个阶段。

---

## 十八、术语表

| 术语 | 含义 |
|---|---|
| **IP** | 可复用的电路块。见 [第一节](#一什么是-ip) |
| **软核 / 固核 / 硬核** | IP 的三种交付形态：RTL / 网表 / 版图 |
| **AXI4-Lite** | Arm 的总线协议子集，无 burst，用于寄存器访问 |
| **MMIO** | Memory-Mapped I/O，把设备寄存器映射进 CPU 地址空间 |
| **BAR** | PCIe 的基址寄存器，决定设备的地址窗口落在哪 |
| **CSR** | 本文档中指 Control/Status Register，即 CPU 可见的 MMIO 寄存器组。**注意**：在 RISC-V 语境里 CSR 指处理器内部的 `csr_*` 接口，是另一回事——见 [1.4](#14-为什么能跟-cpu-交互是分水岭) 的讨论 |
| **W1C** | Write-1-to-Clear：写 1 清该位，写 0 不动作 |
| **W1S** | Write-1-to-Self-clear：写 1 触发动作，硬件自动清零 |
| **OKAY / SLVERR / DECERR** | AXI 的三种响应：正常 / 从端错误 / 译码错误 |
| **tile** | 分块。阵列一次能处理的子矩阵 |
| **drain** | 把阵列里各 PE 的累加器读出、写回存储的过程 |
| **sticky（状态位）** | 置位后保持，直到软件显式清除。用于"错过一次就丢信息"的事件 |
| **posted write** | 不需要等待完成应答的写。PCIe MMIO 写是 posted，可能乱序到达 |
| **doorbell** | 软件用来通知设备"队列里有新内容"的寄存器。见 L2 |
| **MSI-X** | 设备通过向特定地址写数据来触发中断，支持多个向量 |
| **CDC** | Clock Domain Crossing，跨时钟域 |
| **DFT** | Design For Test，可测性设计（扫描链等） |
| **SDC** | Synopsys Design Constraints，时序约束文件 |

---

## 十九、参考

### 仓库内

| 内容 | 位置 |
|---|---|
| 技术栈总览与我们说的"税" | [README.md](../../README.md) |
| 芯片与硬件（脉动阵列 vs 数据流） | [L1 芯片与硬件](../../docs/L1-芯片与硬件/00-芯片与硬件.md) |
| 寄存器与窗口、控制面/数据面分离 | [L2 设备可编程模型](../../docs/L2-设备可编程模型/00-设备可编程模型.md) |
| 设备契约指标（命令粒度、中断聚合度） | [L2 设备契约指标](../../docs/L2-设备可编程模型/01-设备契约指标.md) |
| PE 实现 | [pe.sv](../rtl/pe.sv) |
| PE 自检 | [pe_tb.sv](../tb/pe_tb.sv) |

### 外部

| 主题 | 来源 |
|---|---|
| AXI4-Lite 协议（通道、响应码、`WSTRB`） | Arm AMBA AXI and ACE Protocol Specification |
| MMIO posted write 与 read-back 冲刷 | Linux 内核文档 <https://docs.kernel.org/driver-api/io_ordering.rst> |
| 控制寄存器必须 32 位且对齐访问 | virtio 1.2 规范，MMIO 传输寄存器表 |
| MSI-X 能力结构 | PCI Local Bus Specification 3.0，6.8.2 |
| SRAM 的同步读时序与 memory compiler | foundry / EDA 厂商的 memory compiler 文档 |

---

## 变更记录

| 版本 | 变更 |
|---|---|
| v1.0 | 首版草案。确定 MMIO + AXI4-Lite + 片内 SRAM/序列器路线；`ACC_BITS` 按 32 位推导（`OUT` 字宽 = 1 个累加器，恰好等于 AXI 数据宽度）；补充"什么是 IP"一节 |
