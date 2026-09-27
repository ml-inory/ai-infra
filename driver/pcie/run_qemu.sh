#!/bin/bash
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
if [ -f mypci.ko ]; then
    cp mypci.ko $R/
fi

# 打包
(cd $R && find . | cpio -o -H newc | gzip -9) > $BB/initramfs.cpio.gz
echo "tar to ${BB}/initramfs.cpio.gz"

sudo qemu-system-x86_64 \
  -m 512 -smp 1 \
  -kernel /boot/vmlinuz-$(uname -r) \
  -initrd $BB/initramfs.cpio.gz \
  -append "console=ttyS0 rdinit=/bin/sh" \
  -device edu -nographic -no-reboot
