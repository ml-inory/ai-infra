# CoralNPU × Rocket：把 Google 的开源 NPU 接到 rocket-chip 生成的核上

本文记录把 [`google-coral/coralnpu`](https://github.com/google-coral/coralnpu)（Apache-2.0 的开源 NPU IP）
与 [`ucb-bar/chipyard`](https://github.com/ucb-bar/chipyard)（内含 `rocket-chip` 生成器）接到一个 SoC 里的
设计决策、接口对接、地址映射、启动握手，以及**哪些结论已验证、哪些没有**。

上游代码 checkout 在工程根目录 `coralnpu/` 与 `chipyard/`（不进版本库，见
[`integration/deps.lock`](../integration/deps.lock) 和 [`integration/scripts/fetch-deps.sh`](../integration/scripts/fetch-deps.sh)）。
集成产物在 [`integration/`](../integration/)。

---

## 0. 结论先行

1. **CoralNPU 自带一颗 RISC-V 核，而且这颗核就是它 ML 流水的前端**，不是可以拧下来的"外挂 CPU"。
   它是一颗 4-lane 超标量 RV32IMF(+Zba/Zbb/Zicsr/Zifencei/Zfbfmin) 处理器，标量发射级把
   **vector/matrix 命令**发进命令队列，驱动自己的 RVV 1.0 / VME 后端（`coralnpu/doc/overview.md:3`、`:65-79`、`:118-146`）。
2. **用 rocket-chip 去"顶替"这颗核不是接线，是重做一个 NPU**：要重写前端派发（CQ/uop/RS）、
   重写 TCM/LSU 互连、重写 LLVM 目标。详见 §1。
3. **正确接法**：Rocket 当**宿主/主控 CPU**，CoralNPU 当**挂在系统 AXI4 上的 NPU 外设**，
   它自己的 RV32 控制器继续跑 ML 控制流。这正是 Google 自己在 `coralnpu/doc/integration_guide.md:3`
   预设的用法："integrating CoralNPU as an AXI/TileLink peripheral in a bigger system"。
4. **总线选 AXI4，不选 TileLink-UL**：两边都对 AXI4 原生支持；CoralNPU 的 TL-UL 是 OpenTitan 风格
   （`bus.TLULParameters` / `OpenTitanTileLink.Host2Device` / MuBi4 的 `user.instr_type`），
   与 rocket-chip 的 diplomacy TL 不是同一套 bundle，要额外写适配器。见 §8.2。

这样分工之后，Rocket 提供的是 CoralNPU 给不了的东西——**MMU、Linux、完整工具链**；
CoralNPU 提供的是 Rocket 给不了的东西——**每周期 256 MAC 的矩阵外积引擎 + RVV 后端**。
两边都是各自那半边的正确选择。

---

## 1. 为什么不能把 CoralNPU 的标量核换成 Rocket

（这一节是设计依据，不是背景介绍。想直接看接法可以跳到 §2。）

### 1.1 CoralNPU 的标量核是"ML 前端"，不是通用 CPU

从 `coralnpu/doc/overview.md` 抄关键结构：

| 事实 | 出处 |
| :--- | :--- |
| 4-lane 超标量前端：128-bit 取指 → 4 路译码 → 派发 → retirement buffer | `doc/overview.md:96-103` |
| 标量派发把 **vector/matrix 命令**推进 8 项 Command Queue → 2 级向量译码 → 16 项 uop 队列 → reservation stations | `doc/overview.md:118-134` |
| 后端是解耦的 RVV 1.0（VLEN=128，32 个向量寄存器）+ 实验性 VME/Zvt 矩阵 PE 阵列 | `doc/overview.md:65-88` |
| 自定义指令参与流水：`mpause`（0x08000073）走的是分支单元 `BruOp.MPAUSE` | `hdl/chisel/src/coralnpu/scalar/Decode.scala:760`、`:1265` |

也就是说，"标量核"这条流水线里**已经焊死了 ML 派发语义**：一条向量指令要走 CQ → uop → RS，
retirement 还要异步写回标量/浮点寄存器堆。Rocket 里没有对应结构。

### 1.2 它也不是通用 CPU（所以它需要一个宿主）

| 事实 | 出处 |
| :--- | :--- |
| 宿主能看到的接口只有三个窗口：ITCM / DTCM / 外部控制 CSR | `doc/integration_guide.md:153-162` |
| 跑 bare-metal，目标为 `RV32IMFV (Zve32x)`，不跑操作系统 | Coral NPU [FAQ](https://developers.google.com/coral/guides/faq) |
| 取指默认来自 ITCM；PC 跑出 ITCM 时才回落到 AXI 主设备取指 | `doc/overview.md:193` |
| 宿主启动它的方式是"往 ITCM 灌程序 + 写 PC + 放时钟 + 撤复位 + 轮询状态" | `doc/integration_guide.md:167-218` |

一个没有 MMU、只能从 ITCM 取指、要宿主往里灌程序才能启动的核，
本来就不是用来当主控的。

### 1.3 那"用 Rocket 当它的核"到底要付多少代价

如果坚持要让 Rocket 执行 CoralNPU 的 ML 指令流，需要：

1. 把 CoralNPU 的向量/矩阵后端改成 Rocket 的 **RoCC** 加速器接口，并重新实现
   CQ → uop → RS → 向量 ROB 的派发语义（Rocket 的 RoCC 只有命令/响应两路握手，没有这套结构）；
2. 把 ITCM/DTCM 的 banked SRAM + 本地 crossbar 接进 Rocket 的 TileLink/L1 体系
   （CoralNPU 那边是 `BankedItcm`/`BankedDtcm` + 4x 32b bank，见 `doc/overview.md:183-189`）；
3. 改 LLVM 目标：CoralNPU 的编译器按它自己的 ISA 编（`RV32IMF_Zba_Zbb_Zicsr_Zifencei_Zfbfmin` +
   RVV 1.0 + VME），换成 Rocket 要重做指令选择与向量 lowering；
4. 重做启动/调试路径（`mpause`、retirement buffer、RVVI trace 这些都不是 RISC-V 标准物）。

量级是"数月的研究题"，而且做完之后你得到的**仍然不是 CoralNPU**，只是长得像它的东西。

> 结论：`riscv核用 rocket-chip 生成` 这句话，正确的落点是 **Rocket 生成宿主核**，
> 而不是顶替 NPU 内部那颗控制器核。

---

## 2. 选定拓扑：Rocket 宿主 + CoralNPU 外设

```
        ┌──────────────────── Rocket SoC（chipyard 生成） ─────────────────────┐
        │                                                                      │
        │   Rocket Tile (RV64GC, MMU, 可跑 Linux)                              │
        │        │                                                             │
        │        │ TileLink                                                    │
        │   ┌────▼─────────────────────────────────────────┐                   │
        │   │  SystemBus                                   │                   │
        │   └──┬───────────────────────────────────┬───────┘                   │
        │      │                                   │                           │
        │   mem_axi4                            mmio_axi4                      │
        │      │                                   │                           │
        │   ┌──▼──────────┐                 ┌──────▼───────────────┐           │
        │   │ DDR / 内存   │                 │ 地址译码（NPU 窗口）  │           │
        │   └──▲──────────┘                 └──────┬───────────────┘           │
        └──────┼───────────────────────────────────┼───────────────────────────┘
               │ AXI4 主设备（NPU 主动读写系统内存）  │ AXI4 从设备（宿主读写 ITCM/DTCM/CSR）
               │                                   │
        ┌──────┴───────────────────────────────────▼───────────────────────────┐
        │  CoralNPU（自带 RV32 控制器核 + RVV 1.0 + 可选 VME）                   │
        │    axi_master ──► 系统内存        axi_slave ◄── 宿主（控制面）          │
        └──────────────────────────────────────────────────────────────────────┘
```

**两条通路必须分开看**（这是这类"NPU 外设"集成里最容易混的地方）：

- **控制面**：宿主 → `axi_slave`。带宽小、延迟不敏感，用来灌 ITCM、设 PC、放复位、读状态。
- **数据面**：CoralNPU → `axi_master` → 系统内存/DDR。NPU 自己就是主设备，
  大规模权重/激活数据不该走宿主的 `axi_slave` 窗口。

---

## 3. 接口对接表

CoralNPU 的 AXI 顶层是 `CoreMiniAxi` / `RvvCoreMiniAxi` / `VmeCoreMiniAxi` 三个变体
（`doc/overview.md:51`、`:228-250`），端口由 `hdl/chisel/src/coralnpu/CoreAxi.scala:23-47` 定义：

| CoralNPU 端口 | 方向 | 接到 Rocket SoC 的什么 |
| :--- | :--- | :--- |
| `aclk` / `aresetn` | in | NPU 时钟域。**异步复位、低有效**；内部再经 `RstSync` 同步（`CoreAxi.scala:49-56`） |
| `axi_slave` | 从设备 | 地址译码后的 NPU 窗口（本设计取 `0x7000_0000`），供宿主读写 ITCM/DTCM/CSR |
| `axi_master` | 主设备 | 接系统 AXI4 主设备端口 → DDR/内存（NPU 取指回落 + 数据面） |
| `boot_addr` | in | 复位后载入的起始 PC。程序链接在 0 时**直接接常量 0** 最省事；要给宿主可编程就接一个寄存器 |
| `irq` | in | 常量 0（本设计纯轮询）。要中断就接 PLIC |
| `timer_irq` / `software_irq` | in | 常量 0（这两个是给 NPU 自己当 CPU 用的，宿主集成里用不到） |
| `halted` / `fault` / `wfi` | out | 接 PLIC 或一个 status 寄存器；`fault` 建议至少接进宿主的中断/状态 |
| `dm` | - | 不接（RISC-V debug module 接口，只在调试时用） |
| `te` | in | 常量 0（test-enable，仿真用） |
| `debug`（可选） | out | **只在 `shouldExposeDebugPorts` 为真时存在**（`Parameters.scala:93-96`），仿真看波形用 |

总线参数（`hdl/chisel/src/coralnpu/Parameters.scala:185-188`）：

| 参数 | 值 | 说明 |
| :--- | :--- | :--- |
| `axi2AddrBits` | `xlen`（32） | 地址位宽 |
| `axi2DataBits` | `lsuDataBits` = **128** | 数据位宽。`Parameters.scala:158` 默认 256，但生产目标用 `--lsuDataBits=128` 覆盖（`flags.bzl:20`、`prod/BUILD:50,76`） |
| `axi2IdBits` | 6 | 事务 ID 位宽 |
| `fetchDataBits` | 128 | 取指数据宽度（同样被 `--fetchDataBits=128` 覆盖，`flags.bzl:19`） |

> **生产目标 vs 仿真目标**：要集成就用 `//hdl/chisel/src/coralnpu/prod:*` 那几个目标。
> 仿真目标额外带 `--exposeDebugPorts=True`（`hdl/chisel/src/coralnpu/BUILD:613`），
> 会多出 ~108 个 `io_debug_*` 输出端口（`prod/BUILD:15-21` 有说明）。生产目标是 97 个端口。

AXI4 协议约束（`doc/integration_guide.md:33-117`）——写适配器/译码时必须守：

- NPU **作为主设备**：`prot` 恒 2、`burst` 恒 INCR、`cache` 恒 0、`size` 只发 1/2/4 字节。
  关于 `id`，**要分变体看**（这条比官方文档更细，`prod/BUILD` 里能看出来）：
  - `RvvCoreMiniAxi` / `VmeCoreMiniAxi` 关掉了 AXI 取指（`--enableAxiInstructionFetch=False`，
    `prod/BUILD:75,93`），主设备实际只发 `id = 0`；
  - `CoreMiniAxi`（标量变体）**保留** AXI 取指，取指走 `ARID = 1`、数据走 `0`，
    且核内按 `RID` 把读响应分流回 ibus/ebus（`CoreAxi.scala:283-294`）。
    这种配置下**互连必须把 ARID 回填到 RID**，否则响应会串到错误的总线上。
  → 集成代码里把主设备的 ID 空间声明成 ≥2 个（本仓库的 `CoralNPUAttach` 用 `IdRange(0, 2)`）。
- NPU **作为从设备**：要支持 `size` = 1/2/4/8/16、`burst` = FIXED/INCR/WRAP，并且**必须把 `id` 回填**到响应里。
- **两边都不支持 `user` 信号**。rocket-chip 的 AXI4 bundle 带 `user`/`echo` 字段，对接时置 0 / 忽略。
- **CSR 写不看 `WSTRB`，而是按固定切片取值**（偏移 `0x4` 读的是 `writeData(63,32)`）。
  也就是说它假定**总线已经把窄写数据放到了对应的字节道上**。这条有两个直接后果：
  1. 系统 AXI4 的**数据位宽必须等于 NPU 的 128 位**，否则 32 位写永远落不到 `PC_START` 那一段；
  2. 如果中间插了"把窄写数据统一塞到低位车道"的适配器，`PC_START` 会被静默丢掉
     （表现为：核从 0 取指，而不是你写的地址）。
- **`io_axi_master` 必须被终结**：读请求没人应答会把核挂死。即使是"NPU 不需要访存"的配置，
  也要把它接到一个能返回错误的从设备上，而不是悬空。
- `Parameters.itcmMemoryFile`（`Parameters.scala:190-192`）是**死代码**：全仓库没有 `$readmemh`，
  只有 Verilator/VCS 的 DPI backdoor（`hdl/verilog/Sram.v`）。所以 **ITCM 只能由宿主通过 AXI/DMA 灌入**
  ——这正是本仓库 `sw/host/coralnpu_host.c` 走的路子。

---

## 4. 地址映射

两个视角要分清（搞混是这类集成的经典 bug）：

**系统视角**（宿主 CPU 看到的）

| 区域 | 地址 | 大小 |
| :--- | :--- | :--- |
| CoralNPU 窗口 | `0x7000_0000` | 4 MiB（译码粒度，覆盖 default 与 highmem 两种内部布局） |

**NPU 视角**（NPU 自己 `axi_slave` 上的地址，随 ITCM/DTCM 尺寸配置变化）
—— 取自 `hdl/chisel/src/coralnpu/Parameters.scala:43-56`：

| 区域 | 默认配置 | highmem 配置 | 大小（默认 / highmem） |
| :--- | :--- | :--- | :--- |
| ITCM | `0x0000_0000` | `0x0000_0000` | 8 KiB / ≤1 MiB |
| DTCM | `0x0001_0000` | `0x0010_0000` | 32 KiB / ≤1 MiB |
| CSR | `0x0003_0000` | `0x0020_0000` | 4 KiB |

CSR 寄存器（**这是给宿主的 MMIO 寄存器，不是 RISC-V 的 Zicsr CSR**，见 `doc/integration_guide.md:220-255`）：

| 偏移 | 名字 | 内容 |
| :--- | :--- | :--- |
| `+0x0` | `RESET_CONTROL` | bit0 `RESET`（1=保持复位）、bit1 `CLOCK_GATE`（1=gate 时钟）。**复位值 0b11** |
| `+0x4` | `PC_START` | 起始 PC |
| `+0x8` | `STATUS` | bit0 `HALTED`、bit1 `FAULT`（只读） |

**NPU 的 `axi_master` 出去看到的地址空间**是第三个视角：那是宿主的系统内存（DDR），
需要在系统侧给 NPU 单独开一个主设备端口，并保证它的地址落在 DDR 区域。

---

## 5. 启动握手

严格按 `doc/integration_guide.md:167-218` 的五步（实现在
[`integration/sw/host/coralnpu_host.c`](../integration/sw/host/coralnpu_host.c)）：

```c
coralnpu_hold_in_reset();          // RESET_CONTROL = 0b11（复位 + gate 时钟）
coralnpu_load_itcm(image, len);    // 1. 程序灌进 ITCM（有 DMA 用 DMA，doc:180）
coralnpu_release(0x0);             // 2. 写 PC_START；3. 放时钟(RESET_CONTROL=0b01)；
                                   //    等时钟跑几拍；4. 撤复位(RESET_CONTROL=0b00)
coralnpu_wait_halt(1000000);       // 5. 轮询 STATUS.HALTED / FAULT
```

**时序坑（`doc/integration_guide.md:163-165`）**：核用同步复位。放时钟门控和撤复位之间
**必须让时钟先跑起来、复位保持有效至少一拍**，否则内部 `RstSync` 可能没被正确复位。
在跨时钟域（NPU 时钟 ≠ 宿主时钟）的集成里，这个"等几拍"要按两边频率关系重算，或者干脆做 CDC。

**为什么 `PC_START` 和 `boot_addr` 都存在**：`CoreAxi.scala:39` 的 `boot_addr` 是硬件端口，
复位时载入 `pcStartReg`；`PC_START` CSR 只是把它变成宿主可编程。程序链接在 0 时，
集成里把 `boot_addr` 硬接成 0，宿主的第 2 步可以直接跳过。

**怎么知道 NPU 跑完了**：`mpause` 指令（编码 `0x08000073`，`scalar/Decode.scala:1265`）会让
`STATUS.HALTED` 置 1。这就是验收用的"跑完信号"。

---

## 6. 代码结构

```
integration/
├── deps.lock                     上游依赖的 commit 锁定（coralnpu / chipyard）
├── scripts/
│   ├── fetch-deps.sh             幂等拉取上游（含 schannel→openssl 的坑）
│   ├── emit_coralnpu_sv.sh       bazel 生成 NPU 的 SV + 抽出真实端口表/位宽
│   └── build_npu_program.sh      编 NPU 侧自检程序，出 .bin 给宿主嵌
├── sw/
│   ├── host/                     跑在 Rocket 上的宿主代码
│   │   ├── coralnpu_host.h       地址映射 + CSR 定义 + 接口
│   │   ├── coralnpu_host.c       启动握手五步
│   │   ├── smoke_main.c          端到端自检（返回值判 PASS/FAIL）
│   │   └── npu_image.S           .incbin 把 NPU 二进制嵌进宿主程序
│   └── npu/
│       ├── coralnpu_smoke.S       跑在 CoralNPU 上的最小程序（写 DTCM 标记 + mpause）
│       └── coralnpu_smoke.ld      链接脚本（链接在 0 = ITCM 基址）
├── chisel/                        接进 rocket-chip/chipyard 的集成代码
│   ├── README.md                  怎么挂进 chipyard + 编译前 5 条核对清单
│   └── src/main/scala/coralnpu/rocket/
│       ├── CoralNPUAxi.scala      AXI4(diplomacy) ↔ CoralNPU AxiMasterIO 的字段映射
│       ├── CoralNPUAttach.scala   ClockSinkDomain：AXI4SlaveNode + AXI4MasterNode + CoreAxi
│       └── CoralNPUConfig.scala   chipyard Config + SubsystemInjector（不必改 DigitalTop）
└── notes/                        上游接口的逐行考证（本目录的引用来源）
    ├── coralnpu-axi-port-map.md  CoralNPU 侧：97 个端口 / 位宽 / 启动握手 / 协议约束
    └── chipyard-axi4-attach.md   chipyard+rocket-chip 侧：节点 API / 挂接配方 / 宽度旋钮
```

自检程序的验收链路：

```
宿主写 ITCM ──► NPU 从 ITCM 取指执行 ──► 写 DTCM 标记 ──► mpause 停住
   ──► 宿主读 STATUS.HALTED ──► 宿主从 axi_slave 读回 DTCM 标记比对
```

这条链路一旦通，地址译码、跨时钟/复位、AXI 协议适配就一起被验掉了。

---

## 7. 验证路径（分环境，诚实版）

### 7.1 本机（Windows）能做的

**先说结论：本机已经能真的编译 Chisel 了**（装了一套 portable JDK+sbt 在 `.toolchain/`，
见 `integration/README.md`），所以"能验证什么"这一栏比开工时强了很多。

| 能（已实测） | 不能 |
| :--- | :--- |
| **编译 coralnpu 的 Chisel**（108 个文件，Chisel 7.13.0） | chipyard 的 Verilator 仿真（**本机无 verilator**） |
| **编译集成代码**（`CoralNPUAxi` / `CoralNPUAttach` / `CoralNPUIntegration` + rocket-chip/cde/diplomacy/hardfloat/macros） | `bazel build` 生成 coralnpu 的 SV（**本机无 bazel**） |
| **elaborate + 出 Verilog**：coralnpu 标量变体、集成代码 harness、**以及 Rocket + CoralNPU 完整 SoC** | chipyard 的完整构建（生成器树还缺几个子模块） |
| AXI4 字段映射的机械核对（`lint_axi_mapping.py`） | RVV/FPU 变体（缺 bazel 拉取的 `external/` 第三方 SV） |
| `bash -n` / `fetch-deps.sh` 实跑 / `iverilog -g2012` 解析检查 | |

本机已有的：`iverilog 14.0`（`C:\iverilog\bin`）、cygwin 的 `make 4.4`、`git`、Python 3.14，
以及工作区内的 JDK 21 + sbt 1.11.7。`make` 只在 cygwin 登录 shell 里可见，
详见 [`mini_npu/sim/README.md`](../mini_npu/sim/README.md:25-44)。

### 7.2 Linux / WSL2 上要跑的完整序列

```bash
# 0. 依赖：JDK 17+、sbt、verilator 5.x、riscv64-unknown-elf-gcc、bazel（仅 emit NPU SV 时需要）

# 1. 生成 CoralNPU 的 SystemVerilog（用 prod 目标，别用带 debug 端口的仿真目标）
bash integration/scripts/emit_coralnpu_sv.sh RvvCoreMiniAxi
#   -> integration/build/coralnpu/RvvCoreMiniAxi.sv + 真实端口表 + 位宽
#   等价的手工命令：
#   cd coralnpu && bazel build //hdl/chisel/src/coralnpu/prod:rvv_core_mini_axi_prod_cc_library

# 2. 编 NPU 侧自检程序
bash integration/scripts/build_npu_program.sh

# 3. elaborate + 仿真 Rocket SoC（详见 integration/README.md）
cd chipyard && make -C sims/verilator

# 4. 跑宿主自检，看 PASS
```

**两种拿到 Rocket 核的方式**（工程根目录同时有这两份，`integration/deps.lock` 都锁了 commit）：

| 方式 | 位置 | 说明 |
| :--- | :--- | :--- |
| rocket-chip 独立生成 | `rocket-chip/`（`ucb-bar/rocket-chip`） | 自带 `build.sbt`，能单独 elaborate：`make verilog`（或 `make verilog CONFIG=freechips.rocketchip.system.DefaultSmallConfig`，见 `rocket-chip/README.md:49,53`）。只想验证"核能生成"就走这条 |
| chipyard 包装 | `chipyard/` | 提供 `DigitalTop` + `TestHarness` + Verilator 仿真 + Config 体系。**要挂 NPU 走这条** |

> 本机实测的坑：chipyard 的递归子模块克隆在 TLS 上会中途失败，**失败点之后的子模块工作区是空的**
> （只建了 `.git`，例如 `generators/rocket-chip` 就是空目录）。所以本机额外单独克隆了一份
> `rocket-chip` 作为只读参考与独立生成用；chipyard 那棵树的完整性需要在网络好的环境里补
> （`cd chipyard && git submodule update --init --recursive`，注意 cygwin 下别用 `git -C`）。
> **AXI4 的 bundle/节点 API 是照着这份独立 `rocket-chip` clone 核对过的**（§3 的字段表）。

> **挂接的确切写法**：`integration/chisel/README.md` 里记了一份**逐行核对过**的配方，
> 照抄的是 chipyard 自己的 AXI4 外设范例（`generators/chipyard/src/main/scala/example/GCD.scala`
> 的 `WithGCD(useAXI4 = true)`）：
> `pbus.coupleTo(name) { AXI4InwardClockCrossingHelper(...) := AXI4Buffer() := TLToAXI4() := TLFragmenter(..., holdFirstDeny = true) := _ }`，
> 外设本体继承 `ClockSinkDomain(ClockSinkParameters())`，状态信号用
> `InModuleBody { IO(Output(Bool())).suggestName(...) }` 捅出去。
> 那里也写了**必须注意的位宽约束**：`TLToAXI4()` 的宽度跟总线 `beatBytes` 走，
> 而 NPU 固定 128 位，所以总线要配成 128（`chipyard.config.WithSystemBusWidth(128)`）
> 或插位宽转换——否则 `PC_START` 会静默失效。

### 7.3 未验证清单（**必读**）

本目录里的集成代码**没有在本机编译/仿真过**——本机没有 JDK、sbt、bazel、verilator，也没有 WSL 发行版。
已做的是源码级考证 + 脚本语法检查。上真机前，下面这些点需要逐个确认：

1. **位宽**：已从源码确定是 **128**（`flags.bzl:20` 的 `--lsuDataBits=128`），
   但**仍要在 emit 后核对一次**参数头（`KP_lsuDataBits`）——如果你的目标改过这个 flag，
   就要决定是改系统 AXI4 端口宽度还是插位宽转换。
   注意 `KP_axi2DataBits` **不会**出现在参数头里（它是 `def`，见 `Parameters.scala:241-265` 的发射逻辑）。
2. **Chisel / rocket-chip 版本**：**已实测通过**。CoralNPU 是 `Chisel 7.0.0-RC1 + Scala 2.13.18`
   （`coralnpu/MODULE.bazel:30,57-59`），chipyard `USE_CHISEL7=1` 是 7.13.0 + Scala 2.13.18
   （`chipyard/build.sbt:3-6,105-106`）：coralnpu 的 108 个源文件 + 本仓库的集成代码
   都在 7.13.0 下编过了（§8.1）。
   另外 coralnpu 的 bazel 还依赖 `chipsalliance/rocket-chip` 的 **`f517abb`**
   （`coralnpu/rules/repo_defs.bzl:489-491`），与 chipyard 的 `55bcad0` 不是同一个 commit——
   **这条也实测过了**：coralnpu 用到的 `freechips.rocketchip.util.{AsyncQueue,AsyncQueueParams}`
   在 chipyard 的 `55bcad0` 下编得过，所以这个 pin 差异不咬人。
   （仍保留的残余风险：只覆盖了编译期，运行期行为差异不在这个验证范围内。）
3. **AXI 主设备侧的兼容性**：`RvvCoreMiniAxi`/`VmeCoreMiniAxi` 关了 AXI 取指，主设备只发 `id=0`；
   `CoreMiniAxi`（标量）保留取指，会发 `ARID=1` 并按 `RID` 分流响应（`CoreAxi.scala:283-294`）。
   集成里把主设备 ID 空间声明成 `IdRange(0, 2)` 即可覆盖两个变体；但**互连必须回填 ARID→RID**，
   这点要用 chipyard 那侧的 AXI4 交叉开关实测确认（见 §3 的约束清单）。
4. **CSR 写的字节道问题**：CSR 不看 `WSTRB`，按固定切片取值（偏移 `0x4` 读 `writeData(63,32)`）。
   系统 AXI4 数据位宽必须与 NPU 的 128 位一致，否则 32 位写落不到 `PC_START`。
   这一条最容易在"接上去能跑但 PC 不对"的现象里被误判成启动时序问题。
5. **时钟域**：NPU 的 `aclk` 与宿主总线时钟如果不共享，需要 CDC / 异步 FIFO 或独立时钟域的 AXI 桥，
   而 §5 那个"等几拍"的软性要求也要重新推导。
6. **chipyard 子模块**：`generators/ara` 拉取失败（TLS，与 Rocket 无关）；
   `--shallow-submodules` 还会让子模块落在**分支 tip 而非 pinned SHA**（`git submodule status` 里的 `+`），
   而且递归克隆在中途出错时后续子模块的工作区**是空的**（只有 `.git`）。
   构建前务必确认 `cd chipyard && git submodule update --init --recursive` 干净通过、且
   `generators/rocket-chip/src/main/scala/amba/axi4/Bundles.scala` 真实存在。
   （本机为了绕开这个，额外在工程根目录单独克隆了一份 `rocket-chip`，见 §7.1 的说明；
   注意 cygwin 下的 `git` 是 Windows 版，不认 `/cygdrive/...` 路径，别用 `git -C`。）

### 7.4 本机 elaborate：**连"Rocket + CoralNPU 完整 SoC"都跑通了**

拿到 firtool 之后，本机就能真的 `ChiselStage.emitSystemVerilog(...)` 出 Verilog 了。
验证 harness 在 `integration/build/chisel-integration-check/elaborate-src/Elaborate.scala`，
跑法见 `integration/README.md`。当前结果：

| 目标 | 结果 |
| :--- | :--- |
| **(1a) 标量变体** `CoreMini`（关 RVV/FPU） | ✅ **成功**：生成 `CoreMiniAxi.sv`（**1.3 MB / 27870 行**，文件头写着 `Generated by CIRCT firtool-1.149.0`） |
| (1b) RVV 生产变体 `RvvCoreMini` | ❌ 缺 `external/...` 第三方 SV（见下），本机必然失败 |
| **(2) 本仓库的 `CoralNPUAttach` + mini-harness** | ✅ **成功出 Verilog**：`CoralNPUMiniHarness.sv`（1.4 MB / 29956 行），里面能看到 `CoreMiniAxi npu (...)` 和 `AXI4RAM ram (...)`——diplomacy 图合法、`require()`（id/数据位宽对齐）全过、黑盒全解析、firtool 收尾干净 |
| **(3a) Rocket + CoralNPU 完整 SoC**（纯 rocket-chip，不依赖 chipyard） | ✅ **elaborate 成功** → `RocketCoralNPUSoC.fir`（**55 MB FIRRTL**）：Rocket tile + 总线 + CoralNPU 的 diplomacy 全连通 |
| **(3c) 同一颗 SoC 套一层 harness 出 Verilog** | ✅ **成功** → `RocketCoralNPUTestHarness.sv`（**6.7 MB / 141388 行 / 478 个模块**，顶层模块 `CoralNPUTestHarness`）。里面实测含 `RocketTile`×38、`CoreMini`×26（就是 CoralNPU）、`SimAXIMem`×17、`TLXbar`×178、`CLINT`×210、`PLIC`×70 |
| (3b) 直接把子系统当顶层出 Verilog | ❌ 预期失败：`public module port must have concrete reset type`（见第 10 条） |

**这一轮把"Rocket 主控核 + CoralNPU"这件事在本机真正跑通了**：SoC 能 elaborate、能出 Verilog，且 Verilog 里
两个核都在。剩下没做的是**仿真**（要 Linux + Verilator）和 chipyard 那棵树的完整构建。

**(1a) 顺带量出了真实端口表**（这正是 SV 黑盒路线最需要的东西）：

- 顶层端口 **84** 个：`io_axi_slave_*` **35** + `io_axi_master_*` **35** + `io_aclk`/`io_aresetn` 等；
  **没有 `io_debug_*`**（生产目标不带 debug 端口，与 §3 的说明一致）。
- ID 位宽实测 **6** 位（`io_axi_slave_write_addr_bits_id[5:0]`），地址 **32** 位（`..._addr[31:0]`），
  与 `Parameters.scala:185-188` 推出的一致。
- **端口命名不是 `aw`/`w`/`ar`/`r`**，而是按 coralnpu 自己的 bundle 名平铺：
  `io_axi_slave_{write_addr,write_data,write_resp,read_addr,read_data}_*`。
  rocket-chip 那边是 `aw/w/b/ar/r`，所以写黑盒/适配器时**别按 AXI 惯用名去猜**——
  这一点是靠真 elaborate 才确认的（之前 `emit_coralnpu_sv.sh` 的注释里我猜成 `io_axi_slave_aw_*`，是错的）。

**又一个版本轴：firtool**。Chisel 报错里写得很清楚：
`This version of Chisel (7.13.0) was published against firtool version 1.149.0`。
而 coralnpu 自己 pin 的是 **1.114.0**（`rules/repos.bzl:469`，配套它的 Chisel 7.0.0-RC1）。
用 1.114.0 跑 7.13.0 的 `ChiselStage` 会直接 `FirtoolNonZeroExitCode`（firtool 不认新参数）。
所以源码级集成的版本对齐清单实际是**四条**：Chisel、Scala、rocket-chip pin、**firtool**。
另外 firtool 是通过 **ChiselStage 参数 `--firtool-binary-path`** 指定的
（不是 `-Dfirtool.path` 之类的系统属性，也不是 `FIRTOOL_PATH` 环境变量——
设了不管用，会报 `circt.stage.phases.Exceptions$FirtoolNotFound: Error resolving firtool`）。

这一节暴露的**通用**事实（任何做这个集成都躲不掉）：

1. **`ClockSinkDomain` 的 `clockNode` 必须接时钟源**，否则 diplomacy 直接拒绝：
   `At the following node, ... sink npu.clockNode`（0 个 inward 端口，却有 1 个 inward 参数）。
   → 这正是 `CoralNPUAttach` 继承 `ClockSinkDomain` 的代价，也是 `CoralNPUConfig.scala` 里
   `npu.clockNode := sbus.fixedClockNode` 那一行**不能省**的原因。
2. **coralnpu 的手写 SV 黑盒需要两个资源根**：黑盒引用有两种写法——
   裸文件名（`RstSync.sv`，根 = `coralnpu/hdl/verilog`）和仓库相对路径
   （`hdl/verilog/rvv/design/Aligner.sv`，根 = `coralnpu/`）。只挂一个会分别报
   `BlackBoxNotFoundException`。bazel 那边是靠 `rules/repo_defs.bzl` 一次挂齐的。
   （另外：sbt 的 `unmanagedResourceDirectories` 实测**只 stage 了裸文件那一支**，
   所以 `integration/scripts/stage_sv_resources.ps1` 把 rvv 子树显式拷进工程资源目录。）
3. **`InModuleBody` 必须写在 LazyModule 体里**，不能写在 `lazy val module = new LazyModuleImp(this){}` 内，
   否则报 `InModuleBody invoked outside a LazyModule`
   （rocket-chip 的写法见 `subsystem/Ports.scala:184`）。
4. **输入 bundle 即使永远不用，也必须逐字段驱动**：`npu.io.dm.req` 只写 `valid := false.B` 是不够的，
   firtool 会报 `sink "npu.io_dm_req_bits_address" not fully initialized`。
   **这一条特别阴**：Scala 编译过、Chisel elaborate 也过，**只有最后出 Verilog 时才炸**
   （我第一版就是这么写的，`Scala 编译 ✅ → elaborate ✅ → firtool ❌`）。
   正确写法：`req.bits := 0.U.asTypeOf(req.bits)`。
5. **Chisel 模块只能 elaborate 一次**：同一个 `LazyModule` 实例先 `emitCHIRRTL` 再
   `emitSystemVerilog`，第二次会报
   `attempted to instantiate a Module, but nothing happened`。
   要同时出 FIRRTL 和 Verilog，就得建**两个**实例。

后面 6~10 条是接进**完整 SoC**时才暴露的（都是跑 `RocketCoralNPUSoC` 一步步逼出来的）：

6. **地址图不能和 SoC 自带的对外端口重叠**。rocket-chip 的 `DefaultConfig` 默认开了一个
   对外 MMIO 端口 `ExtBus = 0x6000_0000 + 0x2000_0000`（`subsystem/Configs.scala:289-295`），
   而 NPU 放在 `0x7000_0000` 正好落在里面 → diplomacy 报
   `Ports cannot overlap: AddressSet(0x60000000, 0x1fffffff) AddressSet(0x70000000, 0x3fffff)`。
   chipyard 不冲突是因为它的 `AbstractConfig` 本来就 `WithNoMMIOPort`（`config/AbstractConfig.scala:81`）。
7. **AXI4 ID 位宽必须对齐**。总线那侧经 `TLToAXI4` 出来的 ID 位宽由 diplomacy 决定
   （`idBits = log2Up(master.endId)`，`amba/axi4/Parameters.scala:155`），在 sbus 上实测是 **1 位**，
   而 CoralNPU 默认 `axi2IdBits = 6` → `CoralNPUAttach` 里的 `require` 会当场报出来。
   处理：总线更宽就 `Parameters.augmentId(n)`，总线更窄就直接把 `axi2IdBits` 改成一样
   （RTL 侧本来就参数化，改它就够了）。
8. **`AXI4UserYanker` 在"NPU 当主设备"那条链上不能省**。`AXI4Fragmenter` 会把每个 master 的
   `maxFlight` 清成 `None`（`amba/axi4/Fragmenter.scala:30`），而 `AXI4ToTL` 有硬性
   `require(maxFlight.isDefined)`（`ToTL.scala:31`）→ 报
   `AXI4 must include a transaction maximum per ID to convert to TL`。
   `AXI4UserYanker(Some(n))` 正好把上限补回来（`UserYanker.scala:27-31`）——
   这就是 rocket-chip 自己在 `subsystem/Ports.scala:176-178` 里那么排的原因。
9. **rocket-chip 的黑盒资源也要挂，而且能绕开 `dtc`**：
   - 顶层会引用 `/vsrc/plusarg_reader.v` 等，资源根要包含 `rocket-chip/src/main/resources`
     （或像本仓库这样把 `vsrc`/`csrc` 拷进工程资源目录）。
   - bootrom 的内容是 `if (params.appendDTB) rom ++ subsystem.dtb.contents else rom`
     （`devices/tilelink/BootROM.scala:95`），而 `subsystem.dtb` 会跑 `dtc -O dtb`
     （`resources/DeviceTree.scala:136-137`）→ Windows 上没 dtc 就报 `Failed to run dtc`。
     **解法是 `BootROMParams.appendDTB = false`，而不是删掉 BootROM**——
     删掉会连带拆掉 tile 的 reset vector 广播，报
     `nexus broadcast.node ... 1 outward connections and no inward connections`
     （bootrom 还负责 `driveResetVector`，`BootROM.scala:26,83`）。
     （另：放一个 `dtc.bat` 桩是**没用**的——Java 的 `CreateProcess` 只补 `.exe`，不认 `.bat`。）
10. **顶层必须套一层 harness**。直接把子系统（`ExampleRocketSystem.module`）当顶层出 Verilog，
    firtool 会报 `error: public module port must have concrete reset type`
    ——子系统顶层 IO 里带着抽象 `Reset`（`BaseSubsystem.scala:71` 那组 clock group 端口）。
    照抄 rocket-chip 自己的 `system/TestHarness.scala:13-42` 写一层 harness，把 clock/reset 绑成
    具体的（`ldut.io_clocks.get.elements.values.foreach(_.clock := clock)`）就好了。
    这也解释了 rocket-chip 正常流程生成的顶层为什么叫 **TestHarness** 而不是裸子系统。

还有一个**更关键的发现**：CoralNPU 的 RVV / FPU 变体依赖一批**第三方 SV 库**，它们是 bazel 在构建时
从 GitHub 拉的，**不在 clone 里**：

| 资源路径前缀 | 来自哪个仓库 | pin | 出处 |
| :--- | :--- | :--- | :--- |
| `external/cvfpu/...` | `openhwgroup/cvfpu` | `bb65bdedd077…` | `coralnpu/rules/repos.bzl:97-114` |
| `external/common_cells/...` | `pulp-platform/common_cells` | `6aeee85d0a34…` | `coralnpu/rules/repos.bzl:120-124` |
| `external/fpu_div_sqrt_mvp/...` | PULP | — | `rules/repos.bzl` 里的另外两个 repo |
| `external/RVVI/...` | RVVI | — | 同上 |

它们由 bazel 挂成资源（`coralnpu/rules/chisel.bzl:76-77` 的
`@coralnpu_hw//lib:{common_cells,cvfpu}_resources`），黑盒引用写成 `external/cvfpu/src/fpnew_top.sv`
这种仓库相对路径（`hdl/chisel/src/coralnpu/float/FloatCore.scala:221-297`、`rvv/RvvCore.scala:784-947`）。

**这条对两条路线的取舍很关键**：

- 走 **SV 黑盒**路线时**不受影响**——bazel 生成的是完整交付物（`RvvCoreMiniAxi.sv` 单体，
  或 `.zip` + `filelist.f` 把黑盒文件一起打包），里面已经含这些第三方 SV。
- 走 **源码级集成**路线时，这些库必须一起编进来/挂成资源，否则连 elaborate 都过不去
  （本机实测：`BlackBoxNotFoundException: hdl/verilog/rvv/design/Aligner.sv`）。
  也就是说源码级路线实际上有**三个**版本/依赖要对齐：Chisel 版本、rocket-chip pin、**这批第三方 SV 库**。

---

## 8. 备选路线

### 8.1 源码级集成 vs SV 黑盒（附**实测**结果）

**先给实测结论**：用真实 scalac 把 coralnpu 的 108 个非测试 Chisel 源文件在 **Chisel 7.13.0**
（chipyard `USE_CHISEL7=1` 用的版本）下编了一遍，结果是 **13 个错误，全部是"缺上游源码"，
没有一个是 Chisel 版本漂移**：

| 错误 | 数量 | 真实原因 |
| :--- | :--- | :--- |
| `not found: AsyncQueue / AsyncQueueParams` | 12 | coralnpu 的 RTL import 了 `freechips.rocketchip.util`（`bus/TlulFifoAsync.scala:4`、`bus/Spi2TLULV2.scala:20`）。**这些在集成工程里本来就有**（rocket-chip 源码在编译范围内），所以不算问题 |
| `not found: type ScmInfo` | 1 | `ScmInfo` 是 bazel **生成**的（`coralnpu/utils/scm_info.py:52-58` 产出 `package coralnpu; class ScmInfo`），源码树里没有。单独编译时补一个 stub 即可（本仓库放在 `integration/build/stubs/ScmInfo.scala`） |

复现方式：`pwsh integration/scripts/compile_coralnpu_chisel.ps1`（先跑一次
`setup_local_toolchain.ps1` 装 portable JDK+sbt，见 `integration/README.md`）。

**更进一步：集成代码本身也编过了。** `integration/build/chisel-integration-check/` 把
rocket-chip + cde + diplomacy + hardfloat + macros + coralnpu 的源码和 `integration/chisel/`
里的 `CoralNPUAxi.scala` / `CoralNPUAttach.scala` 一起交给真实 scalac（Chisel 7.13.0），
结果 `[success] done compiling`，产出 4533 个 `.class`（含 `CoralNPUAttach.class`、
`CoralNPUAttach$CoralNPUImpl.class`、`CoralNPUAxi$.class`）。

这一轮**编译器抓出了 4 个真 bug**，都是人手看不出来的：

| 报错 | 真相 |
| :--- | :--- |
| `value user/echo is not a member of IrrevocableIO[AXI4BundleAW]` | `AXI4Bundle` 里 `aw/w/ar` 是 `Irrevocable(...)`，字段在 **`bus.aw.bits.user`**，我写成了 `bus.aw.user`（`CoralNPUAxi.scala` 的 tie-off 段，9 行全错） |
| `unknown parameter name: supportsRead/supportsWrite` | 那是 `AXI4SlaveParameters` 的字段；`AXI4MasterParameters` 没有（AXI4 里传输大小由从设备声明） |
| `found LazyModuleImp, required CoralNPUAttach.this.Impl` | `ClockSinkDomain` 自己定义了 `Impl`，`module` 必须是它的子类（GCD 的写法是 `override lazy val module = new GCDImpl` + `class GCDImpl extends Impl`） |
| （顺带）`maxFlight` 必须给值 | `AXI4ToTL` 里有 `require(maxFlight.isDefined)`（`ToTL.scala:31`），默认 `None` —— 这个是我读源码时先发现的 |

唯一没进这个编译的是 `CoralNPUConfig.scala`：它 `import chipyard.config.*`、
用 `chipyard.config.WithSystemBusWidth(128)` / `AbstractConfig`，要 chipyard 自己的生成器树
（还会牵进 boom/icenet/constellation 一堆），所以它的正确性目前靠"逐行对照 chipyard 现成配置"
（§8 开头那份配方）保证，真正的编译验证留到 chipyard 完整构建。

顺带一个**前瞻性警告**（编译 warning 里看到的）：coralnpu 的 `rvv/RvvCore.scala:690-692` 还在用
`chisel3.BlackBox` / `HasBlackBoxInline` / `HasBlackBoxResource`，这些在 Chisel 7.5 起已废弃、
**Chisel 8 会删掉**。所以将来升 Chisel 8 时 coralnpu 这边要改（现在是 7.13，暂时没事）。

**顺带挖出一个之前不知道的依赖**：coralnpu 的 bazel 构建会去 GitHub 下载
`chipsalliance/rocket-chip`，**锁定在 `f517abb`**（`coralnpu/rules/repo_defs.bzl:489-491`）。
也就是说"源码级集成"除了 Chisel 版本，还有**第二条版本轴**：coralnpu 期望的 rocket-chip
（`f517abb`）与 chipyard 自带的（`55bcad0`）不是同一个 commit。这条要单独验证——见 §7.3。

**两条路的取舍**：

`integration/chisel/` 里走的是**源码级**集成（CoralNPU 的 Chisel 源码编进 chipyard 构建），
好处是不用猜端口名、改参数只改 `Parameters`。如果最终因为 rocket-chip pin 不一致之类的原因编不过，
就回退到黑盒：用 `bash integration/scripts/emit_coralnpu_sv.sh RvvCoreMiniAxi` 生成 SV 并打印
**真实端口表**（生产目标 97 个端口，`io_axi_slave_*` / `io_axi_master_*` 各 39 个），
再照着它写 `BlackBox`。代价是端口名必须逐信号对齐生成物，改不了就得重对一遍。

### 8.2 TileLink-UL 路线（不推荐先做）

CoralNPU 也提供 TL-UL 顶层（`CoreTlul`、`CoralNPUChiselSubsystem`，见 `doc/overview.md:195`），
但它的 TL-UL 是 **OpenTitan 风格**：`bus.TLULParameters`、`OpenTitanTileLink.Host2Device`、
`a.bits.user.instr_type` 用 MuBi4 编码（见 `hdl/chisel/src/soc/CoralNPUChiselSubsystem.scala:87-89,449-473`）。
rocket-chip 那侧是 diplomacy TL（`TLBundleA/D` + `TLClientNode/TLManagerNode`）。
两者语义同源（TileLink 1.8.1 的 Uncached Lightweight），但 bundle 完全不同，
要手写 a/d 全字段映射 + 处理 `instr_type` user bits——比 AXI4 那条路多一层纯手工活。

### 8.3 先单独把 CoralNPU 跑起来

不接 Rocket，先用 CoralNPU 自己的仿真环境把 NPU 程序跑通（`doc/overview.md:254-321` 有完整的
bazel + verilator_sim 流程和 `--backdoor_load` / `--instr_trace` 的用法）。
**强烈建议先做这一步**：集成出问题时，能立刻分辨是 NPU 程序错还是接线错。
