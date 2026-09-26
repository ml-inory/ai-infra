# platform总线设备

它是最简单的总线，不需要真实硬件，纯软件就能演示。很多 SoC 上的片上外设（GPIO、UART、I2C 控制器）都是用 platform 总线描述的。

## 开发环境搭建
```
# 1. 安装编译工具和内核头文件
sudo apt install build-essential linux-headers-$(uname -r)

# 2. 确认内核配置
cd /usr/src/linux-headers-$(uname -r)
ls .config   # 确认 CONFIG_MODULES=y
```

## 编译与加载
```
make                                        # 生成 my_platform_*.ko

# 先加载设备
sudo insmod my_platform_device.ko
sudo dmesg | tail                                # 此时没有 probe，因为没有驱动

# 再加载驱动
sudo insmod my_platform_driver.ko
sudo dmesg | tail
# 输出: probe called! matched device: my_platform_device

# 查看 sysfs 里的绑定关系
ls /sys/bus/platform/devices/my_platform_dev/ -l
# driver -> ../../../bus/platform/drivers/my_platform_dev

# 卸载驱动
sudo rmmod my_platform_driver
sudo dmesg | tail        # 输出: remove called

# 卸载设备
sudo rmmod my_platform_device
```