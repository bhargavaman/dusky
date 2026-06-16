# Hardware Verification & Virtualization Prereqs (Kernel 7.1+)

Before configuring virtualization, we must guarantee your motherboard and the modern Linux kernel (7.1+) are actively cooperating. As of Kernel 7.x, the virtualization stack has entirely deprecated legacy [[VFIO]] Type 1 memory management in favor of **[[IOMMUFD]]**, and heavily relies on hardware-level [[ACS]] (Access Control Services).

## Step 1: UEFI/BIOS Configuration

You must enter your UEFI firmware settings. Modern PCIe passthrough requires far more than just basic CPU virtualization. Locate your **Advanced**, **System Agent**, or **PCIe Subsystem** menus and configure the following:

> [!warning] Essential Settings
> 
> 1. **CPU Virtualization:** Enable **Intel VT-x** or **AMD SVM**.
>     
> 2. **IOMMU / Directed I/O:** Enable **Intel VT-d** or **AMD-Vi**.
>     
> 3. **Above 4G Decoding:** **ENABLED**. (Mandatory for mapping 16GB+ GPUs into a VM).
>     
> 4. **Resizable BAR (ReBAR) / SAM:** **ENABLED**. (Required for zero-bottleneck GPU passthrough).
>     
> 5. **ACS (Access Control Services):** **ENABLED**. (Critical. Ensures the motherboard physically isolates PCIe devices from one another).
>     
> 6. **SR-IOV:** **ENABLED** (If you intend to use vGPU splitting or split network cards).
>     

## Step 2: Verification of the Kernel Environment

```
flowchart LR
    A[1. CPU Flags] --> B[2. IOMMUFD Modules]
    B --> C[3. Active IOMMU Groups]
    C --> D[4. ACS Isolation Map]
```

Once booted into Arch Linux, open your terminal. We will verify the entire chain: CPU features, kernel modules, and hardware isolation.

### 1. Verify CPU Virtualization Support

First, confirm the CPU flags are actively passing to the OS.

```
lscpu | grep -i virtualization
```

> [!check] Expected Output You should see `VT-x` (for Intel) or `AMD-V` (for AMD). If this returns nothing, check your BIOS settings again.

### 2. Verify Modern Kernel Modules (KVM & IOMMUFD)

We need to ensure your running Arch Kernel 7.1.0 was compiled with the modern virtualization stack. The old `CONFIG_KVM_VFIO` is dead; we are looking for `CONFIG_IOMMUFD`.

```
zgrep -E "CONFIG_KVM=|CONFIG_VFIO_PCI=|CONFIG_IOMMUFD=" /proc/config.gz
```

> [!example] Understanding the Results You should see output similar to this:
> 
> `CONFIG_KVM=m` `CONFIG_IOMMUFD=m` `CONFIG_VFIO_PCI=m`
> 
> - **`=y`**: Built directly into the kernel (Always active).
>     
> - **`=m`**: Loadable Module (Arch default, loaded dynamically by QEMU/libvirt).
>     
> - **Missing / `=n`**: The feature is not supported. You would need a custom kernel.
>     

### 3. Verify IOMMU Groups & ACS Isolation (The Crucial Test)

This is the most important step. If your IOMMU is working and ACS is functioning, the kernel will physically separate your PCIe devices into distinct numbered groups in `/sys/kernel/`.

Run this bash script to map out your hardware:

```
for d in /sys/kernel/iommu_groups/*/devices/*; do 
  n=${d#*/iommu_groups/*}; n=${n%%/*}
  printf 'IOMMU Group %s ' "$n"
  lspci -nns "${d##*/}"
done
```

> [!info] How to Read Your IOMMU Map Look through the output for the GPU you want to pass through (e.g., your NVIDIA or AMD card).
> 
> **Success:** Your target GPU and its associated Audio Controller are alone in their own isolated `IOMMU Group` (e.g., both are in `IOMMU Group 15`, and nothing else is). **Failure:** Your GPU is grouped with essential host devices (like your main NVMe drive or USB controller). If this happens, your motherboard's ACS is broken, and you will need an ACS Override Patch.

### 4. Verify Boot Parameters (If Groups are Empty)

If the script in step 3 returned _absolutely nothing_, your kernel has not initialized IOMMU mapping. Verify your bootloader (GRUB or systemd-boot) has the correct parameters:

```
cat /proc/cmdline
```

> [!tip] Required Flags Ensure your boot line includes `iommu=pt` and either `intel_iommu=on` or `amd_iommu=on`.