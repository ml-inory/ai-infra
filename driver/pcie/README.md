# PCIe 设备驱动开发

PCIe（Peripheral Component Interconnect Express）是一种高速串行总线，用来连接 CPU/内存和外部设备（显卡、网卡、NVMe SSD、FPGA 等）。

它和老的 PCI 总线最大的区别：

| 维度 | PCI | PCIe |
|------|-----|------|
| 传输方式 | 并行共享总线 | 点对点串行链路 |
| 拓扑 | 所有设备共享带宽 | 每个设备独占 lane |
| 配置空间 | 256 字节 | 4096 字节（扩展） |
| 速度 | 133 MB/s 级别 | 每 lane 每代翻倍，可到几十 GB/s |
| 热插拔 | 基本不支持 | 原生支持 |

**对驱动开发者来说，PCI 和 PCIe 在软件层几乎一样。** 内核统一用 `pci_driver`、`pci_dev` 这套框架，你不需要区分两者。所以下文说的“PCIe 驱动”，代码上和“PCI 驱动”是同一套——这里讲的写法，你直接拿去写 PCI 驱动也没问题。

## 和 platform 总线的区别

它和 [bus_dev](../bus_dev/README.md) 里的 platform 模型共用同一套匹配机制，区别在于设备是怎么来的：platform 设备是你自己注册出来的，PCIe 设备是开机时内核**扫描总线枚举**出来的。于是驱动要做的事变成两步——先靠 ID 认领设备，再去读设备告诉你的资源。

| | platform | PCIe |
|---|---|---|
| 设备从哪来 | 你写代码注册，或设备树描述 | 内核启动时枚举出来 |
| 匹配依据 | `device.name` / compatible | Vendor ID + Device ID（+ Class） |
| 资源怎么来 | 写在设备树或板级代码里，靠人告诉内核 | 从配置空间（BAR）读出来，内核自己问得出来 |
| 中断 | 多为固定中断号 | MSI/MSI-X，内核分配 |
| 热插拔 | 基本没有 | 支持，设备可以随时来去 |

## 配置空间：设备的身份证

上一节说 PCIe 的资源“内核自己问得出来”，问的就是这段配置空间。内核枚举时读它来认识设备：
```
偏移 0x00: Vendor ID    (2字节)    ← 谁家做的，如 0x8086 = Intel
偏移 0x02: Device ID    (2字节)    ← 哪款芯片
偏移 0x08: Class Code   (3字节)    ← 设备类型，如 0x020000 = 以太网控制器
偏移 0x10~0x24: BAR0~BAR5         ← 6 个地址窗口，映射到设备内部寄存器
偏移 0x3C: IRQ Line / Pin         ← 中断
```
BAR 是 PCIe 最核心的概念：设备把内部寄存器“挂”在 BAR 上，驱动先申请 BAR 这段地址，再 `pci_iomap()` 映射成内核可访问的地址，之后用 `ioread32()` / `iowrite32()` 读写。整个过程中驱动不需要知道物理地址是多少——这正是 platform 设备把地址写死在设备树里时所没有的“可发现性”。

## 核心结构体

前面说 PCI 和 PCIe 是同一套框架，落到代码上就是下面这两个结构体。

### 1. pci_device_id —— 我支持哪些设备
```
static const struct pci_device_id my_pci_ids[] = {
    { PCI_DEVICE(0x1234, 0x11e8) },        // Vendor ID, Device ID
    { PCI_DEVICE_CLASS(0x020000, ~0) },    // 也可以按 Class 匹配一类设备
    { 0, }                                 // 必须以全 0 结尾
};
MODULE_DEVICE_TABLE(pci, my_pci_ids);      // 让热插拔机制也能识别本模块
```

### 2. struct pci_driver —— 驱动本体
```
static struct pci_driver my_pdrv = {
    .name     = "mypci",
    .id_table = my_pci_ids,
    .probe    = my_probe,     // 匹配成功后调用
    .remove   = my_remove,    // 注意：返回 void，不是 int
};

module_pci_driver(my_pdrv);   // 等价于 module_init + pci_register_driver
```

## 匹配与 probe 流程
```
1. 内核枚举总线, 读每个设备的配置空间, 生成 struct pci_dev
        ↓
2. insmod 驱动 → pci_register_driver()
        ↓
3. 总线拿 id_table 里的每一项去比对设备的 Vendor/Device ID
        ↓
4. 匹配成功 → 调用 my_probe(pdev, id)
        ↓
5. probe 里: 使能设备 → 申请 BAR → 映射 BAR → 申请中断 → 再注册字符设备等
        ↓
6. 卸载或拔卡 → remove 里按 probe 的相反顺序释放资源
```
和 [platform_dev](../platform_dev/README.md) 一样是**双向触发**：先插设备后 insmod、先 insmod 后插设备，最后都会走到 `probe`。

## 开发环境搭建
```
# 1. 安装编译工具和内核头文件
sudo apt install build-essential linux-headers-$(uname -r)

# 2. 确认内核配置
cd /usr/src/linux-headers-$(uname -r)
ls .config   # 确认 CONFIG_MODULES=y, CONFIG_PCI=y
```

## 编译与加载
```
make                                   # 生成 mypci.ko

# 查看当前有哪些 PCIe 设备, -nn 会打印 [vendor:device]
lspci -nn

sudo insmod mypci.ko
sudo dmesg | tail                      # 看 probe 有没有被调用

# 如果驱动里已经写了对应 ID, 加载时就会自动 probe; 也可以手动指定 ID 绑定
echo "1234 11e8" | sudo tee /sys/bus/pci/drivers/mypci/new_id

sudo rmmod mypci.ko
sudo dmesg | tail                      # 看 remove 有没有被调用
```

## 没有 PCIe 设备怎么练
不插真卡也能写出完整驱动，用 QEMU 的 edu 教学设备：
```
# 宿主上启动 QEMU, 给它挂一个 edu 设备
qemu-system-x86_64 ... -device edu

# 进虚拟机里确认设备已经在总线上, vendor:device = 1234:11e8
lspci -nn | grep -i 1234
```
edu 的 BAR0 是一块 MMIO 寄存器区，里面有身份寄存器、阶乘寄存器和中断触发寄存器，足够把“枚举 → 匹配 → probe → 映射 BAR → 读写 → 中断”整条链路走通一遍。不想折腾 QEMU 的话，也可以先只写 ID 表和空的 probe/remove，体会一下匹配是怎么发生的。

QEMU 的安装、guest 准备、启动参数、寄存器实测和退出方式整理在 [QEMU.md](QEMU.md)，可以直接照着敲。

## 常用 API
| 机制 | 用途 | 关键 API |
|------|------|---------|
| 识设备 | 读 Vendor/Device ID | `pci_read_config_word` / `pci_match_id` |
| 开设备 | 使能设备、进入 D0 | `pci_enable_device` |
| 资源 | 申请/释放 BAR 区间 | `pci_request_regions` / `pci_release_regions` |
| 映射 | 把 BAR 变成可访问地址 | `pci_iomap` / `pci_iounmap` |
| 读写 | 访问设备寄存器 | `ioread32` / `iowrite32` |
| 中断 | MSI/MSI-X | `pci_alloc_irq_vectors` + `request_irq` |
| 私有数据 | 在回调之间传递结构体 | `pci_get_drvdata` / `pci_set_drvdata` |
| DMA | 设备直访内存 | `dma_alloc_coherent` / `dma_map_single` |

## sysfs 调试
```
# 全部 PCIe 设备, 名字就是 域:总线:设备.功能
ls /sys/bus/pci/devices/

# 看某个设备的身份证和当前驱动
cat /sys/bus/pci/devices/0000:00:03.0/{vendor,device}
ls -l /sys/bus/pci/devices/0000:00:03.0/driver

# 手工解绑/绑定, 调 probe 很顺手
echo 0000:00:03.0 | sudo tee /sys/bus/pci/drivers/mypci/unbind
echo 0000:00:03.0 | sudo tee /sys/bus/pci/drivers/mypci/bind

# 看设备占用的 BAR 和中断
cat /proc/iomem | grep -A2 mypci
cat /proc/interrupts
```

## 容易踩的坑
- `remove` 的返回值是 `void`，不要照着老写法写 `int`。
- `probe` 里每一步都可能失败，失败后要按相反顺序回滚已经申请的资源（习惯用 `goto` + 分段释放）。
- 映射出来的 BAR 必须用 `ioread32` / `iowrite32` 访问，不能当普通指针解引用。
- 释放顺序要反着来：先 `free_irq` 再 `pci_free_irq_vectors`，先 `pci_iounmap` 再 `pci_release_regions`。
- `id_table` 最后一行必须是全 0，否则总线会越界比对。
- 热插拔设备被拔掉后 `probe`/`remove` 可能随时进来，`remove` 之后就不能再碰硬件。
