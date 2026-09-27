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

## 用字符设备把 BAR0 暴露给用户态

字符设备本身不"控制"BAR0——BAR0 还是你在 probe 里 `pci_iomap()` 拿到的那块地址。字符设备只是给用户态开一个 `/dev/xxx` 入口，把 `read` / `write` / `ioctl` / `mmap` 翻译成对这块地址的 `ioread32` / `iowrite32`。所以前半段是"probe 里已有的 BAR 映射"，后半段是"一层文件接口"。

### 先选注册方式

| 方式 | 样板代码 | `/dev` 节点 | 适用 |
|------|---------|------------|------|
| `misc_register()` | 最少 | 自动创建一个 | 一个驱动一个节点，首选 |
| `register_chrdev()` | 少 | 自己 mknod | 老接口，一个主设备号下 256 个次设备共用一套 fops，新代码别用 |
| `alloc_chrdev_region()` + `cdev_init`/`cdev_add` + `class_create`/`device_create` | 最多 | 自动，可多节点 | 一个驱动要多个设备实例、多个 `/dev/mypciN` |

下面的示例走 `misc_register()`：只有一块 edu、只想要一个节点时它最省事。要多个实例就把 `misc` 换成 `cdev` 那套，fops 和下面的写法完全一样。

### 最小示例（mypci_chrdev.c）

`Makefile` 里加一行 `obj-m += mypci_chrdev.o` 就能编。这段在 QEMU 的 edu 上实测跑通（输出见下面的"用户态怎么用"）。

```c
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>

#define DRV_NAME "mypci"

struct mypci_priv {
    struct pci_dev *pdev;
    void __iomem *bar0;
    resource_size_t bar0_len;
    bool dead;                  /* remove 里置位，挡掉已打开的 fd 发来的新请求 */
};

/* 自己再套一层，方便从 miscdevice 反推出 priv */
struct mypci_dev {
    struct mypci_priv priv;
    struct miscdevice misc;
};

/* 通用寄存器读写：用户态给偏移，驱动负责校验和对齐 */
struct mypci_reg {
    u32 offset;
    u32 value;
};

#define MYPCI_REG_READ  _IOWR('m', 1, struct mypci_reg)
#define MYPCI_REG_WRITE _IOW('m', 2, struct mypci_reg)

static int mypci_open(struct inode *inode, struct file *file)
{
    /* misc_open() 会把 miscdevice 放进 file->private_data，从这里反推自己 */
    struct mypci_dev *d = container_of(file->private_data, struct mypci_dev, misc);

    if (d->priv.dead)
        return -ENODEV;

    file->private_data = &d->priv;      /* 后面的回调都靠它拿 bar0 */
    return 0;
}

static int mypci_release(struct inode *inode, struct file *file)
{
    return 0;
}

static long mypci_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct mypci_priv *priv = file->private_data;
    struct mypci_reg reg;

    if (priv->dead)
        return -ENODEV;
    if (copy_from_user(&reg, (void __user *)arg, sizeof(reg)))
        return -EFAULT;

    /* edu 的 MMIO 只接受 4 字节访问，偏移也必须完整落在 BAR0 内 */
    if ((reg.offset & 3) || (resource_size_t)reg.offset + 4 > priv->bar0_len)
        return -EINVAL;

    switch (cmd) {
    case MYPCI_REG_READ:
        reg.value = ioread32(priv->bar0 + reg.offset);
        if (copy_to_user((void __user *)arg, &reg, sizeof(reg)))
            return -EFAULT;
        break;
    case MYPCI_REG_WRITE:
        iowrite32(reg.value, priv->bar0 + reg.offset);
        break;
    default:
        return -ENOTTY;
    }

    return 0;
}

static const struct file_operations mypci_fops = {
    .owner          = THIS_MODULE,      /* 有 fd 打开时 rmmod 会被挡住 */
    .open           = mypci_open,
    .release        = mypci_release,
    .unlocked_ioctl = mypci_ioctl,
};

static int mypci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
    struct mypci_dev *d;
    int ret;

    d = devm_kzalloc(&pdev->dev, sizeof(*d), GFP_KERNEL);
    if (!d)
        return -ENOMEM;

    ret = pci_enable_device(pdev);
    if (ret)
        return ret;

    ret = pci_request_regions(pdev, DRV_NAME);
    if (ret)
        goto err_disable;

    d->priv.bar0 = pci_iomap(pdev, 0, 0);
    if (!d->priv.bar0) {
        ret = -ENOMEM;
        goto err_regions;
    }
    d->priv.pdev     = pdev;
    d->priv.bar0_len = pci_resource_len(pdev, 0);

    /* 注册字符设备：/dev/mypci 由 udev 自动创建 */
    d->misc.minor = MISC_DYNAMIC_MINOR;
    d->misc.name  = DRV_NAME;
    d->misc.fops  = &mypci_fops;
    d->misc.mode  = 0644;               /* 默认是 0600 root，这里放开一点 */

    ret = misc_register(&d->misc);
    if (ret)
        goto err_iounmap;

    pci_set_drvdata(pdev, d);
    pci_info(pdev, "ready: /dev/%s, BAR0 %llu bytes\n",
             d->misc.name, (unsigned long long)d->priv.bar0_len);
    return 0;

err_iounmap:
    pci_iounmap(pdev, d->priv.bar0);
err_regions:
    pci_release_regions(pdev);
err_disable:
    pci_disable_device(pdev);
    return ret;         /* d 是 devm_kzalloc 的，不用 kfree */
}

static void mypci_remove(struct pci_dev *pdev)
{
    struct mypci_dev *d = pci_get_drvdata(pdev);

    /* 先让字符设备下线：挡掉新的 open，也挡掉已打开的 fd 发来的新请求 */
    d->priv.dead = true;
    misc_deregister(&d->misc);

    pci_iounmap(pdev, d->priv.bar0);
    pci_release_regions(pdev);
    pci_disable_device(pdev);
}

static const struct pci_device_id mypci_ids[] = {
    { PCI_DEVICE(0x1234, 0x11e8) },
    { 0, }
};
MODULE_DEVICE_TABLE(pci, mypci_ids);

static struct pci_driver mypci_driver = {
    .name     = DRV_NAME,
    .id_table = mypci_ids,
    .probe    = mypci_probe,
    .remove   = mypci_remove,
};
module_pci_driver(mypci_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Expose PCI BAR0 through a char device (edu demo)");
```

probe 里注册，remove 里反序注销，中间那段 `pci_enable_device` / `pci_request_regions` / `pci_iomap` 就是前面几节讲过的老流程——字符设备只是加在 `pci_iomap` 之后、`pci_set_drvdata` 附近的一步。

### 用户态怎么用

```c
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>

struct mypci_reg { uint32_t offset; uint32_t value; };
#define MYPCI_REG_READ  _IOWR('m', 1, struct mypci_reg)
#define MYPCI_REG_WRITE _IOW('m', 2, struct mypci_reg)

int main(void)
{
    struct mypci_reg r = { 0 };
    int fd = open("/dev/mypci", O_RDWR);

    ioctl(fd, MYPCI_REG_READ, &r);              /* 偏移 0x00：ID 寄存器 */
    printf("ID 寄存器      = %#x\n", r.value);

    r.offset = 0x08; r.value = 5;
    ioctl(fd, MYPCI_REG_WRITE, &r);             /* 让 edu 算 5! */
    do {
        r.offset = 0x20;
        ioctl(fd, MYPCI_REG_READ, &r);          /* 等 COMPUTING 位清零 */
    } while (r.value & 1);

    r.offset = 0x08;
    ioctl(fd, MYPCI_REG_READ, &r);
    printf("edu 算出的 5!  = %u\n", r.value);
    close(fd);
    return 0;
}
```

在 QEMU 的 edu 里实测，启动时自动 insmod，用户态程序跑出来是：

```
[    4.806085] mypci 0000:00:04.0: ready: /dev/mypci, BAR0 1048576 bytes
--- /dev/mypci:
crw-r--r--    1 0        0          10, 262 /dev/mypci
--- 用户态直接读写 BAR0:
ID 寄存器      = 0x10000ed          ← edu 的 identification 寄存器
edu 算出的 5!  = 120
未对齐偏移返回 = -1 (Invalid argument)   ← offset 给 0x01 被驱动挡掉
```

### 顺序和坑

- **remove 的顺序**：先 `misc_deregister()`（或 `cdev_del()`），再 `pci_iounmap()`。`misc_deregister()` 只挡住新的 open，已经打开的 fd 回调照样会被调到，你要是先把 BAR 解映射了，用户态一个 ioctl 就是访问已释放的 vmalloc 区。示例里的 `dead` 标志是最简单的挡法；要求严格就用 kref 数着打开的 fd，等归零再往下走。
- `fops.owner = THIS_MODULE` 必写。有 fd 打开时它会让 `rmmod` 直接失败（内核会给模块引用计数 +1），这是唯一免费的护栏——但它挡不住热插拔触发的 `remove`，所以 `dead` 标志还是得自己管。
- **ioctl 里必须校验偏移**：既要不超出 `pci_resource_len()`，也要满足设备自己的访问宽度（edu 只吃 4 字节，所以非 4 字节对齐直接 `-EINVAL`）。
- 节点权限：misc 设备默认是 `0600 root:root`，普通用户打不开。示例用 `.mode = 0644` 放开；要更细的控制就用 udev 规则，或者 `.nodename` 换个名字。
- 想让用户态直接 `mmap` 整段 BAR0，就在 fops 里加 `mmap` 用 `remap_pfn_range()` + `pci_resource_start(pdev, 0) >> PAGE_SHIFT`，页属性记得 `pgprot_noncached()`，否则会被当普通内存缓存，读到脏数据。
- 一个 misc 设备只有一个节点；要多实例、多节点就换 `alloc_chrdev_region()` + `cdev_add()` + `device_create()` 那条路，fops 部分不用改。

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
- 把 BAR0 挂成字符设备时，`remove` 里要先注销字符设备再 `pci_iounmap`，否则还开着的 fd 会踩到已解映射的地址（见上面"用字符设备把 BAR0 暴露给用户态"）。
