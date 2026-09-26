# 字符设备驱动开发

## 核心流程
```
应用程序 open/read/write
        ↓
   VFS（虚拟文件系统）
        ↓
  cdev + file_operations
        ↓
   硬件操作
```

## 关键结构体
```
// 1. 设备号：主设备号 + 次设备号
dev_t dev = MKDEV(major, minor);

// 2. file_operations：操作函数集合
static struct file_operations fops = {
    .owner   = THIS_MODULE,
    .open    = my_open,
    .release = my_release,
    .read    = my_read,
    .write   = my_write,
};

// 3. cdev：内核中字符设备的表示
struct cdev my_cdev;
```

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
make                                        # 生成 mychardev.ko
sudo insmod mychardev.ko                    # 加载驱动
sudo dmesg | tail                           # 查看major号
sudo mknod /dev/mychardev c <major> 0       # 创建设备节点, 更现代的做法是用 class_create() + device_create()，内核会自动在 /dev 下创建设备节点
echo "hello" | sudo tee /dev/mychardev
sudo cat /dev/mychardev
sudo rm /dev/mychardev
sudo rmmod mychardev.ko
```

## 驱动开发关键机制

| 机制 | 用途 | 关键API |
|------|------|---------|
| `copy_to/from_user` | 用户/内核空间数据拷贝 | 不能直接解引用用户指针 |
| 中断处理 | 响应硬件中断 | `request_irq` / `free_irq` |
| 并发控制 | 多进程访问保护 | `mutex` / `spinlock` / `atomic` |
| 内存分配 | 内核内存 | `kmalloc` / `kzalloc` / `vmalloc` |
| 阻塞/非阻塞 | IO等待 | 等待队列 `wait_event_*` |
| ioctl | 自定义控制命令 | `unlocked_ioctl` |
| 设备树 | 硬件描述（ARM等） | `.dts` 文件 |
| sysfs/procfs | 向用户暴露信息 | `device_create` / `proc_create` |