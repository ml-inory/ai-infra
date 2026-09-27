#!/bin/bash
set -e
# 不管从哪个目录调用，都在脚本所在目录（也就是模块目录）里编译和打包
cd "$(dirname "$0")"

# 先编译，省得忘了 make（失败就退出，别带着旧模块进 guest）
make -s

# 需要一个静态 busybox（busybox-static 包提供 /bin/busybox）
BB=$(mktemp -d); R=$BB/root
mkdir -p $R/bin $R/dev $R/proc $R/sys
cp /bin/busybox $R/bin/busybox
ln -sf busybox $R/bin/sh

# 开机自动执行的脚本：装 applet、设 PATH、挂 proc/sys、加载驱动，然后交给你一个 shell
# （内核会以 rdinit=/init 把它当 PID 1 跑起来）
cat > $R/init <<'EOF'
#!/bin/sh
export PATH=/bin:/sbin
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
# 内核一般已经自动挂好 devtmpfs（CONFIG_DEVTMPFS_MOUNT=y），没挂就补一下
grep -q devtmpfs /proc/mounts || mount -t devtmpfs devtmpfs /dev

# 自动加载驱动；失败不阻塞进入 shell，方便接着调试
if [ -f /mypci.ko ]; then
    insmod /mypci.ko || echo "[init] insmod /mypci.ko 失败，看 dmesg"
fi

echo "=== guest ready: PATH / proc / sys 已就绪 ==="
exec /bin/sh </dev/console >/dev/console 2>&1
EOF
chmod +x $R/init

# 把编译好的驱动一起放进去，guest 里就是 /mypci.ko
if [ -f mypci.ko ]; then
    cp mypci.ko $R/
else
    echo "警告: 当前目录没有 mypci.ko，guest 里不会有驱动（先跑 make）" >&2
fi

# 打包
(cd $R && find . | cpio -o -H newc | gzip -9) > $BB/initramfs.cpio.gz
echo "tar to ${BB}/initramfs.cpio.gz"

	sudo qemu-system-x86_64 \
	  -m 512 -smp 1 \
	  -kernel /boot/vmlinuz-$(uname -r) \
	  -initrd $BB/initramfs.cpio.gz \
	  -append "console=ttyS0 rdinit=/init" \
	  -device edu -nographic -no-reboot
