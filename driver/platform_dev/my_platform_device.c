#include <linux/module.h>
#include <linux/platform_device.h>

static struct platform_device *my_pdev;

static int __init my_dev_init(void)
{
    my_pdev = platform_device_register_simple("my_platform_dev", -1, NULL, 0);
    return PTR_ERR_OR_ZERO(my_pdev);
}

static void __exit my_dev_exit(void)
{
    platform_device_unregister(my_pdev);
}

module_init(my_dev_init);
module_exit(my_dev_exit);
MODULE_LICENSE("GPL");