# mini_npu/sim —— 仿真环境与构建

这个目录只管**怎么把 RTL 跑起来**。设计本身（寄存器、地址映射、中断语义）见 [../doc/ip_design.md](../doc/ip_design.md)。

## 本机工具链（实测）

| 工具 | 位置 | 版本 |
|---|---|---|
| `iverilog` | `C:\iverilog\bin\iverilog.exe`（已在系统 PATH 上） | Icarus Verilog 14.0 (devel) |
| `vvp` | 同上 | — |
| `gtkwave` | `C:\iverilog\bin\gtkwave.exe`（随 Icarus 的 Windows 包一起装） | — |
| `make` | `C:\cygwin64\bin\make.exe` | GNU Make 4.4 |

## 怎么跑

```bash
cd mini_npu/sim
make            # 编译 + 运行
make clean      # 删掉 sim_pe / *.vcd / *.log
gtkwave pe.vcd  # 看波形
```

`make` 做的事就是 `iverilog -g2012 -Wall -o sim_pe $(SRCS)`，然后 `vvp sim_pe`。

## 坑：`make` 只在 cygwin 的登录 shell 里可见

`make` 属于 cygwin 的 `/usr/bin`。而**非登录 shell 不会把 `/usr/bin` 加进 PATH**——它直接继承 Windows 的 PATH，所以 `iverilog` 找得到、`make` 找不到：

```bash
bash -lc 'cd /cygdrive/d/Github/ai-infra/mini_npu/sim && make'   # ✅ /usr/bin 在 PATH 上
bash -c  'cd /cygdrive/d/Github/ai-infra/mini_npu/sim && make'   # ❌ make: command not found
```

诊断方式就是看 PATH 里有没有 `/usr/bin`：

```bash
bash -c 'echo $PATH'
```

从 VS Code 集成终端、PowerShell 或任何脚本里直接调 `make` 都会踩到。三种解法：

1. 用 `bash -lc`（登录 shell，会读 `/etc/profile` 把 PATH 设全）
2. 单次显式补上：`PATH=/usr/bin:$PATH make`
3. 写进 `~/.bashrc`：`export PATH=/usr/bin:$PATH`

## Makefile 的依赖

源文件完全由 `wildcard` 收集，**新增 `.sv` 不用改任何地方**，而且 make 的依赖判断和 iverilog 实际编译用的是同一份列表。

（曾经的坑：编译走一个手工维护的清单文件，而依赖又只看那个清单——改了 `.sv` 之后 make 认为目标已是最新，直接跑上一次编译出来的 `sim_pe`，拿到的是陈旧仿真结果，而且看不出来。清单文件已删除。）

如果将来要给 Verdi / VCS 这类工具喂文件清单，现生成一份即可：

```bash
ls ../rtl/*.sv ../tb/*.sv > filelist.f
```

## 产物

| 文件 | 说明 |
|---|---|
| `sim_pe` | 编译出来的仿真可执行文件，`make clean` 会删 |
| `pe.vcd` | 波形，`pe_tb.sv` 里 `$dumpvars` 生成，`make clean` 会删 |

## 已知的仿真器行为

本机 iverilog 14.0 (devel) 在 `initial` 块里做文件 I/O（`$fscanf` / `$fgets` / `$fdisplay`）时，DUT 的时序 `always` 块会停止正确求值（实测 `psum_out` 出现 555 / 64311 之类与设计不符的值）。所以 [pe_tb.sv](../tb/pe_tb.sv) 的测试向量**硬编码在代码里**，不用文件 I/O。写新的 testbench 时不要踩这个。
