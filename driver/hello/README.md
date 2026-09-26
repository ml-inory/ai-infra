# 第一个驱动：Hello World 模块

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
make                    # 生成 hello.ko
sudo insmod hello.ko    # 加载模块
sudo dmesg | tail       # 查看输出, 打印类似 [78185.488604] Hello, kernel world!
lsmod | grep hello      # 查看已加载模块
sudo rmmod hello        # 卸载模块
sudo dmesg | tail       # 查看输出, 打印类似 [78222.836878] Goodbye, kernel world!
```