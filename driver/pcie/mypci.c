#include <linux/module.h>
#include <linux/pci.h>

/*
 * 骨架说明：
 * 这里只搭出 pci_driver 的框架，具体实现自己写。
 * 编译：make        加载：sudo insmod mypci.ko        卸载：sudo rmmod mypci
 * 调试套路见 README.md，跑 QEMU 练手见 QEMU.md。
 */

/* TODO: 换成你要匹配的 ID。QEMU edu 是 vendor 0x1234 / device 0x11e8 */
static const struct pci_device_id mypci_ids[] = {
    { PCI_DEVICE(0x1234, 0x11e8) },
    { 0, }                                  /* 最后一行必须全 0 */
};
MODULE_DEVICE_TABLE(pci, mypci_ids);

/* 想放自己的状态就用这个结构，probe 里 pci_set_drvdata 挂上去 */
struct mypci_priv {
    struct pci_dev *pdev;
    void __iomem *bar0;
    /* TODO */
    int nirq;
};

static irqreturn_t mypci_irq(int irq, void *dev_id) {
    return IRQ_HANDLED;
}

static int mypci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
    /*
     * TODO: 按顺序认领设备，每一步都可能失败，失败要 goto 回滚：
     *   1. pci_enable_device(pdev)
     *   2. pci_request_regions(pdev, "mypci")
     *   3. pci_iomap(pdev, 0, 0)          拿 BAR0
     *   4. 中断：pci_alloc_irq_vectors + request_irq
     *   5. 对外接口：register_chrdev 等
     *   6. pci_set_drvdata(pdev, priv)
     * 寄存器读写用 ioread32 / iowrite32，别直接解引用指针。
     */

     // 参考资料: https://docs.kernel.org/PCI/pci.html
     // https://docs.kernel.org/driver-api/pci/pci.html
    int ret = 0;
    struct mypci_priv *priv = NULL;
    int nirq;
    int i = 0, j = 0;

    // kzalloc是顺便清零
    // GFP_KERNEL在进程上下文用，分配时可睡眠
    // GFP_ATOMIC在中断上下文用，不能睡
    priv = kzalloc(sizeof(*priv), GFP_KERNEL);
    if (priv == NULL) {
        pci_err(pdev, "kzalloc priv failed!\n");
        return -ENOMEM;
    }

    ret = pci_enable_device(pdev);
    if (ret != 0) {
        pci_err(pdev, "pci_enable_device failed! ret=%d\n", ret);
        goto err_free_priv;
    }
    pci_info(pdev, "pci_enable_device success\n");

    ret = pci_request_regions(pdev, "mypci");
    if (ret != 0) {
        pci_err(pdev, "pci_request_regions failed! ret=%d\n", ret);
        goto err_disable_device;
    }
    pci_info(pdev, "pci_request_regions success\n");

    void __iomem* bar0 = pci_iomap(pdev, 0, 0);
    if (bar0 == NULL) {
        pci_err(pdev, "pci_iomap bar0 failed!\n");
        ret = -ENOMEM;
        goto err_release_regions;
    }
    pci_info(pdev, "pci_iomap success\n");

    nirq = pci_alloc_irq_vectors(pdev, 1, 16,
                            PCI_IRQ_MSIX | PCI_IRQ_MSI | PCI_IRQ_INTX);
    if (nirq <= 0) {
        pci_err(pdev, "pci_alloc_irq_vectors failed! ret=%d\n", nirq);
        ret = nirq;
        goto err_iounmap;
    } 

    priv->pdev = pdev;
    priv->bar0 = bar0;
    priv->nirq = nirq;  
    
    for (i = 0; i < nirq; i++) {
        ret = request_irq(pci_irq_vector(pdev, i), mypci_irq, IRQF_SHARED, "mypci", priv);
        if (ret) {
            pci_err(pdev, "request_irq %d failed! ret=%d\n", pci_irq_vector(pdev, i), ret);
            goto err_free_vectors;
        }
    }          

    pci_info(pdev, "pci probe success\n");
    pci_set_drvdata(pdev, priv);
    return 0;

err_free_vectors:
    for (j = 0; j < i; j++) {
        free_irq(pci_irq_vector(pdev, j), priv);
    }    
    pci_free_irq_vectors(pdev);

err_iounmap:
    pci_iounmap(pdev, bar0);

err_release_regions:
    pci_release_regions(pdev);

err_disable_device:
    pci_disable_device(pdev);

err_free_priv:
    kfree(priv);

    return ret;
}

static void mypci_remove(struct pci_dev *pdev)
{
    /*
     * TODO: 按 probe 的相反顺序释放（remove 返回 void，不要写 int）：
     *   free_irq → pci_free_irq_vectors → pci_iounmap → pci_release_regions → pci_disable_device
     */
    int i = 0;
    struct mypci_priv *priv = pci_get_drvdata(pdev);
    if (!priv)
        return;

    for (i = 0; i < priv->nirq; i++) {
        free_irq(pci_irq_vector(pdev, i), priv);
    }    
    pci_free_irq_vectors(pdev);

    pci_iounmap(pdev, priv->bar0);

    pci_release_regions(pdev);
    pci_info(pdev, "pci_release_regions\n");

    pci_disable_device(pdev);
    pci_info(pdev, "pci_disable_device\n");

    kfree(priv);
}

static struct pci_driver mypci_driver = {
    .name     = "mypci",
    .id_table = mypci_ids,
    .probe    = mypci_probe,
    .remove   = mypci_remove,
};

module_pci_driver(mypci_driver);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("ml-inory");
MODULE_DESCRIPTION("PCIe driver skeleton");
