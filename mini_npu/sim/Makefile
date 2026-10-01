SIM		= sim_pe

SRCS	= $(wildcard ../rtl/*.sv) $(wildcard ../tb/*.sv)

all: run

# 依赖必须列出源文件本身。曾经只依赖一个手工清单文件（filelist.f），改了 .sv
# 之后 make 认为目标已是最新，直接跑上一次编译出来的 sim_pe —— 拿到的是陈旧
# 的仿真结果。现在用 wildcard 直接收集源文件，不需要再单独维护清单。
$(SIM): $(SRCS)
	iverilog -g2012 -Wall -o $(SIM) $(SRCS)

run: $(SIM)
	vvp $(SIM)

clean:
	rm -f $(SIM) *.vcd *.log

.PHONY: all run clean
