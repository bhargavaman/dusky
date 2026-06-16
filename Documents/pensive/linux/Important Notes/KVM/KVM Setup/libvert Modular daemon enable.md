# Enabling Modular Libvirt Daemons

In this step, we are configuring the "engine" that runs your virtual machines. We are switching from the old-school "Monolithic" mode to the modern "Modular" mode.

## Why are we doing this?

By default, older setups used a **Monolithic** daemon (`libvirtd`). This is like having one giant manager trying to do everyone's job at once—it handles storage, networks, and the VMs themselves. It works, but it unnecessarily hogs system memory.

We are switching to **Modular** daemons using **Systemd Socket Activation**. This is like having a team of specialists. Because we are only enabling their _sockets_ (the communication doorways), the actual daemons stay completely asleep. If you aren't touching the network, the network manager uses 0MB of RAM. It only wakes up the microsecond it receives a request, making your system incredibly efficient.

> [!INFO] Service Breakdown: What are we enabling?
> 
> Here is exactly what each specialist piece of the puzzle does:
> 
> - **`virtqemud`** (QEMU Daemon): The most important one. It manages the compute part of the VM (CPU/RAM).
>     
> - **`virtnetworkd`** (Network Daemon): Creates virtual networks (NAT/Bridging) so VMs can connect to the internet.
>     
> - **`virtnodedevd`** (Node Device Daemon): Handles physical hardware passthrough (PCIe/USB/GPU).
>     
> - **`virtstoraged`** (Storage Daemon): Manages the virtual hard drives (.qcow2) and storage pools.
>     
> - **`virtinterfaced`** (Interface Daemon): Manages physical host network interfaces.
>     
> - **`virtnwfilterd`** (Network Filter Daemon): Acts like a firewall, controlling network traffic rules.
>     
> - **`virtsecretd`** (Secret Daemon): Safely stores passwords and encryption keys needed by your VMs.
>     
> - **`virtproxyd`** (Proxy Daemon): Acts as a translator for legacy applications that still think the monolithic `libvirtd` is running.
>     

## Step 1: Kill the Monolithic Daemon Securely

Before starting the modular specialists, we must completely eradicate the old manager and its listening sockets. Otherwise, systemd will experience port conflicts.

```
# Stop, disable, and mask both the service and all legacy sockets
sudo systemctl stop libvirtd.service libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket
sudo systemctl disable libvirtd.service libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket
sudo systemctl mask libvirtd.service libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket
```

## Step 2: Enable the Modular Sockets

We need to enable the connection points (`.socket`) for every driver.

> [!WARNING] Critical Systemd Rule
> 
> Do **NOT** enable the `.service` units. If you enable the services, they will run 24/7. By only enabling the `.socket` units, systemd handles waking them up automatically when needed.

Copy and paste this loop to enable the sockets:

```
for drv in qemu interface network nodedev nwfilter secret storage proxy; do \
  sudo systemctl enable virt${drv}d.socket virt${drv}d-ro.socket virt${drv}d-admin.socket; \
done
```

Now, manually start the sockets for this current session (ignoring any warnings about missing modules, as some daemons don't utilize all three socket types):

```
for drv in qemu interface network nodedev nwfilter secret storage proxy; do \
  sudo systemctl start virt${drv}d.socket virt${drv}d-ro.socket virt${drv}d-admin.socket; \
done
```

## Step 3: Apply Changes

For systemd to clean up the IPC namespaces and transition to the modular architecture smoothly, reboot your computer.

```
systemctl reboot
```

## Appendix: How to Undo (Disable)

> [!WARNING] Reverting
> 
> If you need to revert these changes later, stop and disable the modular sockets.

**1. Stop the running sockets & services:**

```
for drv in qemu interface network nodedev nwfilter secret storage proxy; do \
  sudo systemctl stop virt${drv}d.service virt${drv}d.socket virt${drv}d-ro.socket virt${drv}d-admin.socket; \
done
```

**2. Disable them from starting on boot:**

```
for drv in qemu interface network nodedev nwfilter secret storage proxy; do \
  sudo systemctl disable virt${drv}d.socket virt${drv}d-ro.socket virt${drv}d-admin.socket; \
done
```

**3. Unmask the legacy daemon:**

```
sudo systemctl unmask libvirtd.service libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket
```