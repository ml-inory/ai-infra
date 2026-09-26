# 总线设备模型

## 对比字符设备
在字符设备示例里，设备和驱动是手动绑在一起的：
```
alloc_chrdev_region(...);
cdev_init(&my_cdev, &fops);
cdev_add(&my_cdev, dev_num, 1);
```

这里没有“发现设备”的过程，设备是你自己凭空造出来的。

但真实硬件（PCIe、USB、I2C、平台设备）不是这样。真实世界里：

- **设备是客观存在的**：内核启动或热插拔时，总线会去扫描，发现“总线上有个东西”。

- **驱动是后来才加载的**：你的 .ko 可能在内核启动很久之后才 insmod。

- **两者需要被自动匹配**：内核需要一套机制，让“发现的设备”和“注册的驱动”能自动对上号。

这套机制就是 **总线（bus）**。内核里的总线不是硬件总线本身，而是一个**软件抽象层**，负责三件事：
```
        ┌─────────────┐
        │    bus      │  ← 负责匹配
        │  (pci/i2c/  │
        │  platform)  │
        └──────┬──────┘
               │
      ┌────────┴────────┐
      │                 │
┌─────▼─────┐     ┌─────▼─────┐
│  device   │     │  driver   │
│ (硬件信息) │     │ (操作方法) │
└───────────┘     └───────────┘
```
- device：描述“有这么个硬件”，带上它的 ID、资源（地址、中断）。

- driver：描述“我会操作这类硬件”，带上它支持的 ID 列表和 probe/remove。

- bus：当 device 或 driver 任一注册时，去比对双方的 ID，匹配成功就调用 driver 的 probe。

## 三个核心结构

### 1. struct bus_type —— 总线
```
struct bus_type {
    const char *name;              // 总线名，如 "pci"、"i2c"、"platform"
    int (*match)(struct device *dev, struct device_driver *drv); // 匹配函数
    int (*probe)(struct device *dev);   // 可选，旧式
    int (*remove)(struct device *dev);
    ...
};
```
```match``` 是总线的灵魂。它决定“这个 device 和这个 driver 是不是一对”。不同总线有不同的匹配规则：
| 总线 | 匹配依据 |
|------|---------|
| platform | `device.name` == `driver.name`，或设备树 compatible |
| i2c | `i2c_device_id` 或设备树 compatible |
| pci | Vendor ID + Device ID |
| usb | Vendor ID + Product ID |

### 2. struct device —— 设备

```
struct device {
    struct kobject kobj;           // 对应 /sys/devices/... 下的节点
    struct bus_type *bus;          // 它挂在哪条总线上
    struct device_driver *driver;  // 匹配到的驱动
    void *platform_data;           // 板级私有数据
    ...
};
```
这是所有设备的基类。platform_device、pci_dev、i2c_client 都内嵌了一个 struct device。所以你在 /sys/devices/ 里看到的层次结构，就是这个结构体树的反映。

### 3. struct device_driver —— 驱动

```
struct device_driver {
    const char *name;
    struct bus_type *bus;          // 它属于哪条总线
    int (*probe)(struct device *dev);
    int (*remove)(struct device *dev);
    ...
};
```
同样，platform_driver、pci_driver、i2c_driver 都内嵌了它。

## 匹配流程

假设你 ```insmod``` 了一个驱动，或者内核刚枚举出一个设备，流程是这样的：
```
1. 设备或驱动注册
        ↓
2. 总线遍历另一侧的列表
   device 注册 → 遍历 driver 列表
   driver 注册 → 遍历 device 列表
        ↓
3. 对每一对调用 bus->match(dev, drv)
        ↓
4. match 返回非 0（匹配成功）
        ↓
5. 调用 driver->probe(dev)
        ↓
6. probe 里初始化硬件、注册字符设备/块设备等
```

**双向触发**：不管谁先注册，只要另一方出现，总线都会去重新匹配。这就是为什么你可以先 ```insmod``` 驱动、后插设备，也可以反过来。

在 ```/sys/bus/<bus>/``` 下能看到三个目录：
```
ls /sys/bus/platform/
# devices/   drivers/   drivers_autoprobe  ...
```

devices/ 是这条总线上所有设备，drivers/ 是所有驱动。你甚至可以看到匹配后 devices/xxx/driver 这个符号链接指向了对应的 driver。

具体例子见[platform_dev](../platform_dev/README.md)