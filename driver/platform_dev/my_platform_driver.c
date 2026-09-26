#include <linux/module.h>
#include <linux/platform_device.h>

static int my_probe(struct platform_device *pdev)
{
    dev_info(&pdev->dev, "probe called! matched device: %s\n", pdev->name);
    return 0;
}

static void my_remove(struct platform_device *pdev)
{
    dev_info(&pdev->dev, "remove called\n");
}

static struct platform_driver my_pdrv = {
    .probe  = my_probe,
    .remove = my_remove,
    .driver = {
        .name = "my_platform_dev",   // 必须和设备名一致才会匹配
    },
};

module_platform_driver(my_pdrv);
MODULE_LICENSE("GPL");