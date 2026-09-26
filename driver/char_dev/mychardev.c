#include <linux/module.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/uaccess.h>

#define DEV_NAME "mychardev"
static dev_t dev_num;
static struct cdev my_cdev;
static char kbuf[128];

static int my_open(struct inode *inode, struct file *file)
{
    printk(KERN_INFO "Device opened\n");
    return 0;
}

static ssize_t my_read(struct file *file, char __user *buf,
                       size_t len, loff_t *off)
{
    // 1. 计算实际要拷贝的长度，取用户请求长度和内核缓冲区长度的较小值
    size_t n = min(len, sizeof(kbuf));

    // 2. 可以在这里加一个偏移量检查，防止重复读取时越界
    if (*off >= sizeof(kbuf))
        return 0; // 表示文件结束

    n = min(n, sizeof(kbuf) - (size_t)*off);

    // 3. 如果拷贝失败（返回值非0），则返回错误码
    if (copy_to_user(buf, kbuf + *off, n))
        return -EFAULT;

    // 4. 更新偏移量并返回实际拷贝的字节数
    *off += n;
    return n;
}

static ssize_t my_write(struct file *file, const char __user *buf,
                        size_t len, loff_t *off)
{
    if (copy_from_user(kbuf, buf, len))
        return -EFAULT;
    return len;
}

static int my_release(struct inode *inode, struct file *file)
{
    return 0;
}

static struct file_operations fops = {
    .owner   = THIS_MODULE,
    .open    = my_open,
    .read    = my_read,
    .write   = my_write,
    .release = my_release,
};

static int __init mydev_init(void)
{
    // 动态分配设备号
    alloc_chrdev_region(&dev_num, 0, 1, DEV_NAME);
    cdev_init(&my_cdev, &fops);
    cdev_add(&my_cdev, dev_num, 1);
    printk(KERN_INFO "Registered major=%d minor=%d\n",
           MAJOR(dev_num), MINOR(dev_num));
    return 0;
}

static void __exit mydev_exit(void)
{
    cdev_del(&my_cdev);
    unregister_chrdev_region(dev_num, 1);
}

module_init(mydev_init);
module_exit(mydev_exit);
MODULE_LICENSE("GPL");