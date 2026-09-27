# QEMU 与 edu 设备使用指南

[README.md](README.md) 里提到“没有 PCIe 真卡时用 QEMU 的 edu 设备练”，这篇是配套的操作手册：怎么装 QEMU、怎么启动带 edu 的虚拟机、进了 guest 之后怎么确认设备、怎么读它的寄存器、以及怎么退出。

文中所有命令和输出都在 QEMU 10.2.1 + Ubuntu（内核 7.0.0-30-generic，无 `/dev/kvm`）上实际跑过，输出是真实抓下来的。

## 先明确一件事

edu 是 QEMU 模拟出来的设备，只存在于 **guest** 的虚拟 PCI 总线上。宿主机 `lspci` 永远看不到 `1234:11e8`。所以用 edu 练驱动，编译和 `insmod` 都在 guest 里做。

## edu 设备速览

| 项目 | 值（实测） |
|------|-----------|
| Vendor / Device ID | `0x1234` / `0x11e8` |
| Class | `0x00ff00`（`lspci` 显示 `Unclassified device [00ff]`） |
| Revision | `0x10` |
| Subsystem | `1af4:1100` |
| BAR0 | 32 位内存，1 MiB，非预取 |
| 中断 | 中断引脚 A（传统 INTx）+ MSI（1 个向量，支持 64 位地址） |
| 功能 | BAR0 上的 MMIO 寄存器、阶乘计算、DMA |

寄存器细节见本文第三节，或直接看 QEMU 源码 `hw/misc/edu.c`。

## 一、安装

### 1.1 宿主机装 QEMU

```
sudo apt update
sudo apt install -y qemu-system-x86 qemu-utils busybox-static cpio

# 确认装好了，并且 edu 设备存在
qemu-system-x86_64 --version
qemu-system-x86_64 -device help | grep '^name "edu"'      # → name "edu", bus PCI
```

其他平台：Fedora 用 `sudo dnf install qemu-system-x86 qemu-img busybox cpio`，macOS 用 `brew install qemu`，`-device edu` 同样可用。

再确认有没有硬件加速：

```
ls -l /dev/kvm
```

有 `/dev/kvm` 就在启动命令里加 `-enable-kvm -cpu host`；没有（嵌套虚拟化没开、或者你本身就在虚拟机里）就用纯软件模拟 TCG，慢一些但完全够用。本文的机器没有 `/dev/kvm`，下面所有命令都是 TCG 下跑出来的。

### 1.2 先选一个 guest

| 方案 | 怎么做 | 优点 | 缺点 |
|------|--------|------|------|
| A | 复用宿主机内核 + busybox initramfs | 不用下载镜像，几秒启动；guest 内核和宿主机是同一个，宿主机编的 `.ko` 直接能用 | 没有网络和包管理，只能跑基础命令 |
| B | 云镜像 + cloud-init | 完整发行版，能 `apt install`，有 `lspci` | 要下载几百 MB，TCG 下启动慢 |
| C | 发行版 ISO 正常装机 | 最接近真机 | 最费事，装一次要很久 |

入门推荐 A，需要长期开发、要装工具链就用 B。

### 1.3 方案 A：做一个最小 initramfs（实测）

```
# 需要一个静态 busybox（busybox-static 包提供 /bin/busybox）
BB=$(mktemp -d); R=$BB/root
mkdir -p $R/bin $R/dev $R/proc $R/sys
cp /bin/busybox $R/bin/busybox
ln -sf busybox $R/bin/sh

# 设备节点必须用 root 建，cpio 会原样打进去
sudo mknod -m 600 $R/dev/console c 5 1
sudo mknod -m 666 $R/dev/null    c 1 3
sudo mknod -m 600 $R/dev/mem     c 1 1      # 只有想用 devmem 读 BAR 才需要

# 把编译好的驱动一起放进去，guest 里就是 /mypci.ko
cp mypci.ko $R/

# 打包
(cd $R && find . | cpio -o -H newc | gzip -9) > $BB/initramfs.cpio.gz
```

注意：Ubuntu 上 `/boot/vmlinuz-$(uname -r)` 是 `600 root` 权限，所以启动 QEMU 要用 `sudo`，或者先把内核拷出来放开权限。

### 1.4 方案 B：云镜像

```
mkdir -p ~/edu-vm && cd ~/edu-vm
curl -LO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
qemu-img create -f qcow2 -b noble-server-cloudimg-amd64.img -F qcow2 disk.qcow2 20G

cat > user-data <<'EOF'
#cloud-config
password: ubuntu
chpasswd: { expire: false }
ssh_pwauth: true
package_update: true
packages: [build-essential, pciutils, linux-headers-generic]
EOF
printf 'instance-id: edu01\nlocal-hostname: edu\n' > meta-data

sudo apt install -y cloud-image-utils
cloud-localds seed.img user-data meta-data
```

这里装 `linux-headers-generic` 而不是 `linux-headers-$(uname -r)`，是因为云镜像首次启动可能会顺带升级内核，写成具体版本容易对不上。

### 1.5 guest 里的编译环境（B / C 方案用）

```
sudo apt install -y build-essential linux-headers-$(uname -r) pciutils
make
sudo insmod mypci.ko
```

方案 A 不用装这些：guest 用的就是宿主机的内核镜像，头文件在宿主机上；宿主机编出来的 `.ko` 直接扔进 initramfs 就能 `insmod`（下面第二节有实测）。

## 二、启动

### 2.1 最小骨架

```
qemu-system-x86_64 -M pc -device edu -nographic
```

| 参数 | 作用 |
|------|------|
| `-M pc` | i440fx 机型（默认），edu 表现为普通 conventional PCI 端点 |
| `-M q35` | PCIe 机型，想体会 PCIe 拓扑用这个（edu 默认落在 `00:03.0`） |
| `-device edu` | 挂一块 edu；要两块就写两遍，或用 `-device edu,id=edu1` 起名字 |
| `-nographic` | 串口和 QEMU monitor 都走当前终端 |
| `-enable-kvm -cpu host` | 有 `/dev/kvm` 时加，速度差一个数量级 |

### 2.2 方案 A 的完整启动命令（实测）

```
sudo qemu-system-x86_64 \
  -m 512 -smp 1 \
  -kernel /boot/vmlinuz-$(uname -r) \
  -initrd $BB/initramfs.cpio.gz \
  -append "console=ttyS0 rdinit=/bin/sh" \
  -device edu -nographic -no-reboot
```

大约 5 秒进 shell。进去先做两件事，否则 `mount`、`cat` 都会报 `not found`：

```
export PATH=/bin:/sbin
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
```

第一次用 busybox 最容易卡在这里：applet 没装到 PATH 上，`mount: not found`。

### 2.3 方案 B 的完整启动命令

```
qemu-system-x86_64 -m 2048 -smp 2 \
  -drive file=disk.qcow2,if=virtio \
  -drive file=seed.img,if=virtio,format=raw \
  -device edu -nographic -no-reboot
```

登录用户名和密码都是 `ubuntu`（cloud-init 里设的）。

### 2.4 不装系统，先在 QEMU 侧确认设备（实测）

最快的验证方式，不需要任何 guest：

```
printf 'info pci\nquit\n' | qemu-system-x86_64 -M pc -device edu -display none -S -monitor stdio
```

```
  Bus  0, device   4, function 0:
    Class 0255: PCI device 1234:11e8
      PCI subsystem 1af4:1100
      IRQ 0, pin A
      BAR0: 32 bit memory (not mapped)
```

（`Class 0255` 是 QEMU monitor 自己的写法，进 guest 用 `lspci` 看会是 `Unclassified device [00ff]`。）

### 2.5 不重启就加/拔设备（热插拔，实测）

把 monitor 挂到一个 socket 上，就可以随时加设备：

```
# 启动时加上 -monitor unix:/tmp/edu-mon.sock,server,nowait
sudo nc -U /tmp/edu-mon.sock <<< 'device_add edu,id=edu9'   # 插入
sudo nc -U /tmp/edu-mon.sock <<< 'device_del edu9'          # 拔出
```

实测 guest 内核立刻枚举出新设备：

```
[ 26.320657] pci 0000:00:05.0: [1234:11e8] type 00 class 0x00ff00 conventional PCI endpoint
[ 26.321864] pci 0000:00:05.0: BAR 0 [mem 0x00000000-0x000fffff]
[ 26.338784] pci 0000:00:05.0: BAR 0 [mem 0x20000000-0x200fffff]: assigned
```

也可以直接在终端里 Ctrl-A c 进 monitor 手动敲（见第四节）。注意热插拔后总线号和 BAR 地址都会变，别在驱动里写死。

### 2.6 guest 里确认设备

```
lspci -nn | grep 1234                    # 1234:11e8 ... Unclassified device [00ff]
lspci -vv -s 00:04.0                     # 看 BAR 大小、Capabilities（MSI）

cat /sys/bus/pci/devices/0000:00:04.0/{vendor,device,class,revision,irq}
head -1 /sys/bus/pci/devices/0000:00:04.0/resource    # BAR0 起止地址和属性
```

内核日志里还有枚举过程（实测）：

```
pci 0000:00:04.0: [1234:11e8] type 00 class 0x00ff00 conventional PCI endpoint
pci 0000:00:04.0: BAR 0 [mem 0xfea00000-0xfeafffff]
```

没装 `pciutils` 的 guest 可以直接读 sysfs：`for d in /sys/bus/pci/devices/*; do echo $d; cat $d/vendor $d/device; done`。

## 三、edu 的 MMIO 寄存器

下面的表按 QEMU 10.2.1 的 `hw/misc/edu.c` 核对过。

| 偏移 | 名字 | 读 | 写 |
|------|------|----|----|
| `0x00` | identification | 恒为 `0x010000ED`（高字节 `0x01` 主版本、次字节 `0x00` 次版本，低字节 `ED` 是彩蛋） | 忽略 |
| `0x04` | live check | 返回上次写入值的按位取反 | 保存 `~val` |
| `0x08` | factorial | 读结果 | 写 n 启动计算（异步线程，先看 `0x20` 的 COMPUTING 位） |
| `0x20` | status | bit0 COMPUTING、bit7 IRQFACT | 只认 bit7：置 1 表示“算完发中断”，写 0 关闭 |
| `0x24` | interrupt status | 当前挂起的中断位：bit0 阶乘、bit8 DMA | 忽略 |
| `0x60` | raise interrupt | — | 写位掩码，主动触发中断 |
| `0x64` | lower interrupt | — | 写位掩码，清除中断 |
| `0x80` | DMA 源地址 | 回读 | 写入 |
| `0x88` | DMA 目标地址 | 回读 | 写入 |
| `0x90` | DMA 字节数 | 回读 | 写入 |
| `0x98` | DMA 命令 | 回读 | bit0 RUN、bit1 方向、bit2 完成后中断 |

### 用 devmem 直接验证（实测）

在 guest 里以 root 执行；`/dev/mem` 节点按 1.3 建好，`devmem` 来自 busybox：

```
D=/sys/bus/pci/devices/0000:00:04.0
B=$(head -1 $D/resource | cut -d' ' -f1)     # 实测 0x00000000fea00000

devmem $B 32                                 # 0x010000ED  ← ID 寄存器

devmem $((B+4)) 32 0x11223344                # live check 写入
devmem $((B+4)) 32                           # 0xEEDDCCBB  ← ~0x11223344

devmem $((B+8)) 32 6                         # 计算 6!
while [ $(( $(devmem $((B+0x20)) 32) & 1 )) -ne 0 ]; do :; done
devmem $((B+8)) 32                           # 0x000002D0 = 720

devmem $((B+0x60)) 32 1                      # raise factorial 中断
devmem $((B+0x24)) 32                        # 0x00000001
devmem $((B+0x64)) 32 1                      # lower
devmem $((B+0x24)) 32                        # 0x00000000
```

驱动一旦用 `pci_request_regions()` 占住这段 BAR，`devmem` 就读不到了——这是正常现象，此时改用驱动里的 `ioread32()`。

### 两个容易踩的坑

**MMIO 访问宽度**：edu 的寄存器只接受 4 字节访问（`0x80` 以上还接受 8 字节）。用 `ioread8()` / `ioread16()` 只会拿到全 1，读不出真值，这是“驱动上去没反应”的常见原因。

**DMA 地址**：

- 寄存器里有一端必须写成设备内部缓冲的地址 `0x40000 ~ 0x40fff`（4 KiB），另一端才是 guest 物理地址。越界时 QEMU 日志会打 `EDU: DMA range ... out of bounds`，这次传输被丢掉。
- guest 侧地址会被 `dma_mask`（默认 `0x0FFFFFFF`）按位与。所以 `-m` 给超过 256 MB 时，DMA 缓冲必须落在低 256 MB 内，否则数据会写到别处。要么启动时写 `-device edu,dma_mask=0xffffffff`，要么驱动里用 DMA32 方式分配。

刚开始练的时候可以先不碰 DMA，把阶乘和中断跑通就已经覆盖了驱动的完整主链路。

## 四、退出

| 从哪里退 | 怎么做 | 说明 |
|----------|--------|------|
| guest 里 | `poweroff` / `shutdown -h now` | 有正常 init 的发行版 |
| guest 里（busybox） | `poweroff -f` | initramfs 里没有 init 处理信号，必须加 `-f`（实测不加没反应） |
| 宿主机终端 | 按 `Ctrl-A` 松开再按 `x` | 立刻退出（实测） |
| 宿主机终端 | `Ctrl-A` + `c` 进 monitor，再敲 `quit` | 先看状态再退出（实测） |
| 宿主机终端 | `Ctrl-A` + `h` | 列出全部快捷键 |
| 另一个终端 | `pkill` | 兜底 |

```
# 看看有哪些 QEMU 在跑
pgrep -a qemu-system-x86_64
pkill -f 'qemu-system-x86_64.*edu'
```

两个开关会改变退出行为：

- `-no-reboot`：guest 重启时直接退出 QEMU，而不是重新启动一遍（本文例子都带着它，方便脚本化）
- `-no-shutdown`：guest 关机时 QEMU 不退出，停在 monitor 里，方便检查最后状态

注意 `-nographic` 下 `Ctrl-A` 是 QEMU 的转义前缀，所以 guest 里想给 shell 发真正的 `Ctrl-A` 要按两次。

## 五、常见坑

1. `/boot/vmlinuz-$(uname -r)` 是 `600 root`，QEMU 得用 `sudo` 启动，或者先把内核拷出来。
2. 没有 `/dev/kvm` 就只能 TCG，启动慢、跑得慢，但功能完整。
3. busybox initramfs 里先 `/bin/busybox --install -s /bin`，否则 `mount` / `cat` / `ls` 全都 `not found`。
4. guest 里编译驱动必须用 guest 自己的内核头文件。方案 A 是例外：guest 就是宿主机内核，宿主机编的 `.ko` 直接能 `insmod`。加载时会打 `loading out-of-tree module taints kernel`，属于正常提示。
5. BAR 地址每次启动都可能变（实测同一台机器一次是 `0xfea00000`，热插拔那次是 `0x20000000`），永远从 `/sys/bus/pci/devices/*/resource` 读，别写死。
6. i440fx 上 edu 是 conventional PCI，没有 PCIe 扩展能力；想看 PCIe 拓扑就用 `-M q35`。
7. edu 只存在于 guest，宿主机 `lspci` 看不到它，也没法直通给宿主机用。
8. 内核自带驱动不会抢 edu，你的驱动 `insmod` 后一定会走到 `probe`。

## 六、速查

| 想干的事 | 命令 |
|----------|------|
| 装 QEMU | `sudo apt install -y qemu-system-x86 qemu-utils busybox-static cpio` |
| 确认 edu 存在 | `qemu-system-x86_64 -device help \| grep '^name "edu"'` |
| 看有没有 KVM | `ls -l /dev/kvm` |
| 只看 QEMU 侧设备 | `printf 'info pci\nquit\n' \| qemu-system-x86_64 -M pc -device edu -display none -S -monitor stdio` |
| 起最简 guest | 见 2.2（方案 A）/ 2.3（方案 B） |
| 运行时加设备 | `sudo nc -U /tmp/edu-mon.sock <<< 'device_add edu,id=edu9'` |
| guest 里认设备 | `lspci -nn \| grep 1234`，或读 `/sys/bus/pci/devices/*/{vendor,device}` |
| 读寄存器 | `devmem $((BAR0+偏移)) 32` |
| guest 关机 | `poweroff`（busybox 用 `poweroff -f`） |
| 强制退出 QEMU | 终端按 `Ctrl-A` 再按 `x` |
