# Muxless Laptop GPU Passthrough with Looking Glass

> **Target Stack — June 2026**
> Arch Linux · Kernel 7.x · systemd 260 · QEMU ≥ 9.x · libvirt ≥ 10.x · Windows 11 Guest

---

## Architecture: The Full Pipeline

On a muxless (Optimus) laptop the NVIDIA GPU has no physical video output — all
pixels are routed through the weaker Intel/AMD iGPU. When you pass the NVIDIA
card to a KVM guest, it becomes headless. The following three-component stack
solves this entirely in software:

```
Windows Guest                   Kernel / Shared Memory             Arch Host
─────────────────────────────   ─────────────────────────────────  ─────────────────────
NVIDIA GPU (passed through)  →  KVMFR module  →  /dev/kvmfr0  →  looking-glass-client
VDD (fake monitor)               (DMA char device, zero-copy)        (renders on your display)
LG Host App (frame capture)
```

| Component | Role |
|---|---|
| **VDD** (Virtual Display Driver) | Creates a ghost monitor for the NVIDIA GPU so Windows has a render target |
| **Looking Glass Host** | Runs in Windows; captures the NVIDIA framebuffer and writes it to shared memory |
| **KVMFR module** | Kernel character device (`/dev/kvmfr0`) — provides a true DMA zero-copy window between guest and host |
| **looking-glass-client** | Reads `/dev/kvmfr0` on the host and renders the Windows desktop in a window |
| **xfreerdp3** | FreeRDP v3 rescue bridge — used to configure Windows drivers while the emulated display is disabled |

---

## Prerequisites Checklist

Before starting, confirm your system meets these requirements:

- [ ] PCI passthrough (IOMMU, VFIO) is already working — the NVIDIA GPU is
      bound to `vfio-pci` and assigned to your VM
- [ ] Your VM is a Windows 11 guest managed by **libvirt** (virt-manager is fine; it
      uses libvirt as its back end)
- [ ] You are a member of the `kvm` group: `groups $USER | grep kvm`
- [ ] `dkms` and `linux-headers` (matching your running kernel) are installed

---

## Phase 1 — Host Kernel Layer: The KVMFR Module

The KVMFR (KVM Frame Relay) kernel module replaces the legacy `/dev/shm` POSIX
shared-memory approach entirely. It exposes `/dev/kvmfr0` as a proper character
device that the NVIDIA GPU's DMA engine can write directly, cutting out all
intermediate copies. There is no race condition on startup and no manual `chown`
needed after the VM launches.

### 1.1 Install Packages

```bash
# AUR: Looking Glass client (bleeding-edge git build)
paru -S --needed looking-glass-git

# AUR: KVMFR DKMS kernel module (git, matches the client source tree)
paru -S --needed looking-glass-module-dkms-git

# Official repos: FreeRDP v3 rescue bridge + DKMS framework
sudo pacman -S --needed freerdp dkms
```

> **Package note:** `looking-glass-git` builds the Linux **client** viewer.
> `looking-glass-module-dkms-git` builds the **KVMFR kernel module** and
> registers it with DKMS so it auto-rebuilds on every kernel upgrade. Both are
> required; neither includes the other.
>
> The Looking Glass **host application** (the Windows-side frame capturer) must
> version-match the client exactly. For a `-git` client, grab the matching host
> binary from the Looking Glass CI artifacts or build it from the same commit.
> See: <https://looking-glass.io/downloads>

### 1.2 Calculate Your IVSHMEM Memory Size

Choose a size based on your target resolution. **Get this right before
proceeding** — it must be consistent across the kernel module config, the libvirt
XML, and determines how much contiguous RAM is reserved.

**Formula (SDR):** `width × height × 4 × 2 ÷ 1024 ÷ 1024 + 10`, then round up
to the nearest power of 2.

**Formula (HDR):** Replace the `× 4` with `× 8` (64-bit pixels).

| Resolution | SDR (MiB) | HDR (MiB) |
|---|---|---|
| 1920×1080 (1080p) | **32** | 64 |
| 1920×1200 (1200p) | **32** | 64 |
| 2560×1440 (1440p) | **64** | 128 |
| 3840×2160 (4K) | **128** | 256 |

> **Practical recommendation:** Use **128 MiB** as a safe default. It covers 4K
> SDR headroom and has negligible cost beyond the reserved RAM. If you intend to
> experiment with HDR capture (note: compositor support on Linux is still
> limited as of mid-2026), use 256 MiB for a 4K target.

### 1.3 Configure the Module

Create the modprobe options file. Replace `128` with your chosen size if different:

```bash
sudo tee /etc/modprobe.d/kvmfr.conf << 'EOF'
# KVMFR Looking Glass — static IVSHMEM device size
# Must match the 'size' field (in bytes) in the libvirt XML qemu:commandline block.
# Byte equivalent: size_MiB × 1048576
options kvmfr static_size_mb=128
EOF
```

Create the systemd-modules-load entry so the module is always loaded at boot
**before** your VM can start:

```bash
sudo tee /etc/modules-load.d/kvmfr.conf << 'EOF'
# Load KVMFR before any VM that uses it
kvmfr
EOF
```

### 1.4 Configure udev Permissions

The udev rule grants the `kvm` group read/write access to `/dev/kvmfr0` and
sets the `uaccess` tag so the currently logged-in seat user also gets access
automatically — no hardcoded username required.

> **Critical:** The rule file must sort lexically **before** `73-seat-late.rules`
> for the `uaccess` tag to be processed correctly. The filename `70-kvmfr.rules`
> satisfies this.

```bash
sudo tee /etc/udev/rules.d/70-kvmfr.rules << 'EOF'
SUBSYSTEM=="kvmfr", GROUP="kvm", MODE="0660", TAG+="uaccess"
EOF
```

### 1.5 Load and Verify

Load the module immediately for this session without requiring a reboot:

```bash
sudo modprobe kvmfr
```

Verify the character device was created correctly:

```bash
ls -l /dev/kvmfr0
```

Expected output — look for the `c` at the start (character device):

```
crw-rw---- 1 root kvm 242, 0 Jun 16 10:00 /dev/kvmfr0
```

Confirm the module announcement in dmesg:

```bash
dmesg | grep kvmfr
# Expected: kvmfr: creating 1 static devices
```

> **Warning — regular file trap:** If QEMU ever starts before the KVMFR module
> is loaded, it will create `/dev/kvmfr0` as a regular file instead of a
> character device. The symptom is `ls -l` showing a permissions string that
> starts with `-` (not `c`) or a non-zero file size. If this happens:
> ```bash
> sudo rm /dev/kvmfr0
> sudo modprobe kvmfr
> ```
> The correct fix is ensuring the module is loaded at boot (step 1.3) so QEMU
> never races against it.

### 1.6 Configure libvirt cgroups Device ACL

libvirt uses cgroups to restrict which device files QEMU processes can open.
`/dev/kvmfr0` must be explicitly whitelisted or the VM will fail to start.

Open the libvirt QEMU configuration file:

```bash
sudo nvim /etc/libvirt/qemu.conf
```

Find the commented-out `cgroup_device_acl` block (search for `cgroup_device_acl`)
and replace it with the following uncommented version. Preserve any devices
already listed in your file — the list below is a safe superset of the defaults:

```
cgroup_device_acl = [
    "/dev/null", "/dev/full", "/dev/zero",
    "/dev/random", "/dev/urandom",
    "/dev/ptmx", "/dev/kvm",
    "/dev/kvmfr0"
]
```

Apply the change:

```bash
sudo systemctl restart libvirtd.service
```

---

## Phase 2 — VM XML: Wiring the IVSHMEM Bridge

We need to add two things to the libvirt domain XML:

1. The `qemu` XML namespace declaration on the root `<domain>` tag
2. A `<qemu:commandline>` block that passes the KVMFR device to QEMU

These **must** be added in a single editing session. Saving after adding only
the namespace (but before the commandline block) will cause libvirt to reject
the edit.

### 2.1 Open the VM XML

```bash
# Confirm your VM name first
sudo virsh list --all

# Open the XML — replace win11 with your VM name
sudo EDITOR=nvim virsh edit win11
```

### 2.2 Add the QEMU Namespace to the Root Domain Tag

Locate the first line of the document — the `<domain>` opening tag. It will
look something like:

```xml
<domain type='kvm'>
```

Modify it to declare the QEMU namespace:

```xml
<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>
```

### 2.3 Add the KVMFR Command-Line Block

Scroll to the **very bottom** of the file, just before the closing `</domain>`
tag (after `</devices>`). Paste the following block:

```xml
  <qemu:commandline>
    <qemu:arg value="-device"/>
    <qemu:arg value="{'driver':'ivshmem-plain','id':'shmem0','memdev':'looking-glass'}"/>
    <qemu:arg value="-object"/>
    <qemu:arg value="{'qom-type':'memory-backend-file','id':'looking-glass','mem-path':'/dev/kvmfr0','size':134217728,'share':true}"/>
  </qemu:commandline>
```

> **Size field:** The `'size'` value is in **bytes**. It must match your
> `static_size_mb` setting from Phase 1 exactly.
>
> | `static_size_mb` | `'size'` in bytes |
> |---|---|
> | 32 | `33554432` |
> | 64 | `67108864` |
> | **128** | **`134217728`** |
> | 256 | `268435456` |
>
> This guide uses 128 MiB → `134217728`. Adjust both files to match if you
> chose a different size.

> **Legacy syntax warning:** If you use the old flat-string QEMU syntax
> (`ivshmem-plain,id=shmem0,...`) on QEMU ≥ 6.2 with libvirt ≥ 7.9, QEMU will
> abort with a `PCI: slot 1 function 0 not available` error. The JSON
> single-quote syntax shown above is the correct modern form.

### 2.4 Where the Block Goes (Context)

```xml
      <!-- ... rest of your <devices> section ... -->
      <memballoon model="none"/>
    </devices>

    <!-- ↓ PASTE qemu:commandline HERE — outside </devices>, inside </domain> ↓ -->
    <qemu:commandline>
      <qemu:arg value="-device"/>
      <qemu:arg value="{'driver':'ivshmem-plain','id':'shmem0','memdev':'looking-glass'}"/>
      <qemu:arg value="-object"/>
      <qemu:arg value="{'qom-type':'memory-backend-file','id':'looking-glass','mem-path':'/dev/kvmfr0','size':134217728,'share':true}"/>
    </qemu:commandline>

  </domain>
```

> **memballoon:** The `<memballoon model="none"/>` shown above is strongly
> recommended for all GPU passthrough setups. The VirtIO memory balloon device
> causes significant latency in passthrough environments. Find the existing
> `<memballoon>` tag in your XML and change its model attribute to `none`.

### 2.5 Recommended: VirtIO Input Devices

For proper keyboard and mouse handling through the SPICE channel (which Looking
Glass uses for input), ensure your `<devices>` section contains:

```xml
<!-- Replace or supplement any existing input devices with these -->
<input type='mouse' bus='virtio'/>
<input type='keyboard' bus='virtio'/>
```

Remove any `<input type='tablet'/>` device. The VirtIO mouse driver also
requires the **vioinput** driver from the `virtio-win` package installed in
the Windows guest.

### 2.6 Apply and Test

Save the XML and exit the editor. libvirt will validate the file on save. If
it rejects it, re-open and check that both the namespace and the commandline
block are present.

Start the VM:

```bash
sudo virsh start win11
```

Confirm the VM started without errors:

```bash
sudo virsh domstate win11
# Expected: running
```

---

## Phase 3 — Windows Guest: Drivers and Virtual Display

### 3.1 Find the VM's IP Address

```bash
# Wait a few seconds for the guest DHCP lease to appear
sudo virsh domifaddr win11
```

Note the IPv4 address (e.g., `192.168.122.45`). You will use this for RDP.

### 3.2 Connect via FreeRDP v3 (Rescue Bridge)

The Arch Linux `freerdp` package ships the v3 binary as `xfreerdp3` (with
binary versioning enabled at build time to coexist with the legacy `freerdp2`
package):

```bash
xfreerdp3 \
  /u:"Administrator" \
  /v:192.168.122.45 \
  /dynamic-resolution \
  /size:1920x1080 \
  /cert:ignore
```

Replace the IP and credentials as appropriate. This RDP session is your rescue
bridge — you will use it to configure drivers while the emulated display is
disabled.

### 3.3 Install VIRTIO-WIN Drivers

Inside the RDP session, if you have not already done so, install the VirtIO
Windows drivers. These are required for the VirtIO keyboard and mouse inputs
configured in Phase 2.

Download the ISO from: <https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/>

Mount it and run `virtio-win-guest-tools.exe` to install all drivers at once,
including **vioinput** (VirtIO keyboard/mouse) and **SPICE Guest Agent**
(clipboard synchronization).

### 3.4 Install the NVIDIA Guest Driver

Install the standard NVIDIA driver for your GPU within the Windows VM via RDP.
Download from <https://www.nvidia.com/Download/index.aspx> and run the
installer normally. A reboot will be required.

### 3.5 Install the Looking Glass Host Application

The Looking Glass **host** application runs in Windows and is responsible for
capturing the NVIDIA framebuffer and writing it to the KVMFR device. Its
version **must exactly match** the client you installed on the host.

For a `looking-glass-git` client, obtain the corresponding host binary:
- **Option A (recommended):** Download the matching nightly host binary from
  the Looking Glass CI: <https://looking-glass.io/downloads>
- **Option B:** Build from source using the same git commit

Install it to `C:\Program Files\Looking Glass (host)\` and configure it to run
at startup (e.g., as a Scheduled Task or via `looking-glass-host.ini`).

### 3.6 Disable the Emulated Display Adapter

The emulated QXLAN/Microsoft Basic Display Adapter must be disabled to force
Windows to use the passed-through NVIDIA GPU as its primary render target. Do
this via RDP so you retain display access after the emulated adapter goes dark.

Inside the RDP session:

1. Open **Device Manager** (`devmgmt.msc`)
2. Expand **Display Adapters**
3. Right-click **Red Hat QXL controller** (or **Microsoft Basic Display Adapter**
   if QXL is not present)
4. Select **Disable device → Yes**

Windows will lose the emulated display and scan for the next available GPU. The
NVIDIA driver should activate and Windows will render to the NVIDIA card. Your
RDP session may stutter briefly but will remain active since RDP is an
independent channel.

### 3.7 Install VDD — Virtual Display Driver

With no physical monitor connected to the NVIDIA GPU, Windows will not have a
render target and the GPU will go idle (Code 43 error in some cases). The VDD
(Virtual Display Driver) solves this by presenting a fake monitor to Windows
via the IddCx 1.10 class extension framework — the same mechanism real monitors
use, but entirely in software.

**Download:** <https://github.com/VirtualDrivers/Virtual-Display-Driver/releases>

Download the latest release zip. Inside the RDP session, extract it and install
the driver. Two methods are available:

**Method A — VDC (Virtual Driver Control) GUI (recommended):**
Run `VirtualDriverControl.exe` from the release package. Use the GUI to install
the driver and confirm a virtual monitor appears.

**Method B — Manual INF install:**
Right-click `VirtualDisplayDriver.inf` → **Install**. Windows will install the
driver certificate and activate the virtual monitor.

Verify success: Right-click the desktop → **Display Settings**. You should see
two displays: your RDP session and the new virtual monitor attached to the NVIDIA
GPU.

### 3.8 Configure vdd_settings.xml

The VDD configuration file lives at `C:\VirtualDisplayDriver\vdd_settings.xml`.
Edit it to match your target resolution and refresh rate. Below is a minimal
configuration for a 2560×1440 @ 144 Hz SDR setup:

```xml
<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>

  <monitors>
    <count>1</count>
  </monitors>

  <!-- Tell VDD to prefer your NVIDIA GPU for the virtual display -->
  <gpu>
    <friendlyname>default</friendlyname>
  </gpu>

  <!-- Global refresh rates offered to Windows for all resolutions -->
  <global>
    <g_refresh_rate>60</g_refresh_rate>
    <g_refresh_rate>120</g_refresh_rate>
    <g_refresh_rate>144</g_refresh_rate>
    <g_refresh_rate>165</g_refresh_rate>
    <g_refresh_rate>240</g_refresh_rate>
  </global>

  <!-- Explicit resolution list (must match or exceed your Looking Glass target) -->
  <resolutions>
    <resolution>
      <width>1920</width>
      <height>1080</height>
      <refresh_rate>144</refresh_rate>
    </resolution>
    <resolution>
      <width>2560</width>
      <height>1440</height>
      <refresh_rate>144</refresh_rate>
    </resolution>
    <resolution>
      <width>3840</width>
      <height>2160</height>
      <refresh_rate>60</refresh_rate>
    </resolution>
  </resolutions>

  <colour>
    <!-- Set SDR10bit=true for 10-bit SDR output. HDRPlus for HDR (Win 11 23H2+) -->
    <SDR10bit>false</SDR10bit>
    <HDRPlus>false</HDRPlus>
    <ColourFormat>RGB</ColourFormat>
  </colour>

  <cursor>
    <HardwareCursor>true</HardwareCursor>
    <CursorMaxX>128</CursorMaxX>
    <CursorMaxY>128</CursorMaxY>
    <AlphaCursorSupport>true</AlphaCursorSupport>
  </cursor>

</vdd_settings>
```

After editing, reload the VDD driver (right-click the VDD tray icon → Reload,
or via VDC) for changes to take effect.

> **Set the virtual monitor as primary:** In Display Settings, drag the VDD
> monitor to the left so it is Monitor 1. Confirm the NVIDIA adapter is shown
> as the associated GPU. This ensures the Looking Glass host captures the correct
> output.

---

## Phase 4 — Client Configuration and Launch

### 4.1 Create the Configuration File

The `looking-glass-client` binary reads its settings from
`~/.config/looking-glass/client.ini` (XDG standard path). The directory is
created automatically on first launch; create the file manually now.

```bash
mkdir -p ~/.config/looking-glass
nvim ~/.config/looking-glass/client.ini
```

Paste the following and adjust to your environment:

```ini
; Looking Glass Client Configuration
; June 2026 — KVMFR module / Arch Linux

[app]
; Point to the KVMFR character device, not /dev/shm
shmFile=/dev/kvmfr0
; Allow DMA transfers — required for KVMFR zero-copy performance
allowDMA=yes

[win]
; Auto-resize the client window to match the guest resolution on connect
autoResize=yes
; Keep the correct aspect ratio when the window is resized manually
keepAspect=yes
; Prevent the host screensaver from triggering while focused on the VM
noScreensaver=yes

[input]
; escapeKey uses Linux input event codes (not SDL scancodes, not key names).
; 97 = KEY_RIGHTCTRL — Right Control is the capture/escape toggle key.
; This replaces the old CLI flag: -m KEY_RIGHTCTRL
escapeKey=97
; Use raw mouse input in capture mode — essential for accurate gaming input
rawMouse=yes
; Hide the host cursor while inside the LG window
hideCursor=yes

[egl]
; vsync=no minimises input latency — recommended for gaming
vsync=no
```

> **escapeKey integer reference — common values:**
>
> | Key | Linux event code (`escapeKey=`) |
> |---|---|
> | Scroll Lock (default) | `70` |
> | **Right Control** | **`97`** |
> | Right Alt | `100` |
> | Right Shift | `54` |
>
> These are standard Linux input subsystem keycodes. Run
> `looking-glass-client --help | grep -A2 escapeKey` to see the full list, or
> pass `escapeKey=help` to print all valid values at startup.

### 4.2 Launch the Client

```bash
looking-glass-client
```

No flags are required — all configuration is now in `client.ini`. The client
will connect to `/dev/kvmfr0` automatically and start streaming frames from the
Windows guest.

**Default key bindings (escape key = Right Ctrl):**

| Combo | Action |
|---|---|
| `RCtrl` | Toggle mouse/keyboard capture mode |
| `RCtrl` + `Q` | Quit Looking Glass |
| `RCtrl` + `F` | Toggle fullscreen |
| `RCtrl` + `D` | Toggle FPS overlay |
| `RCtrl` + `O` | Enter overlay/configuration mode |
| `RCtrl` + `I` | Toggle SPICE input |

---

## Phase 5 — Troubleshooting

### Black Screen on Connect

Looking Glass opens but the window is black. The NVIDIA GPU is not sending
frames because no active display output is configured.

**Fix:**
1. Force shutdown the VM: `sudo virsh destroy win11`
2. Start it again: `sudo virsh start win11`
3. Launch the client: `looking-glass-client`
4. Click the black LG window to focus it
5. Press `Right Ctrl` to enter capture mode (cursor disappears)
6. Blindly send `Win` + `P`, wait 1 second, then press `Down`, `Down`, `Enter`

This navigates the Windows "Project" menu from "PC screen only" to "Extend",
waking the NVIDIA driver and starting frame output into the KVMFR buffer.

### `/dev/kvmfr0` Is a Regular File (Not a Character Device)

Symptom: `ls -l /dev/kvmfr0` shows `-rw` instead of `crw`.

QEMU started before the KVMFR module was loaded and created a regular file at
that path. Fix:

```bash
sudo virsh destroy win11
sudo rm /dev/kvmfr0
sudo modprobe kvmfr
sudo virsh start win11
```

To prevent recurrence, ensure `/etc/modules-load.d/kvmfr.conf` is in place
(Phase 1.3) so the module is always loaded before any VM starts.

### VM Fails to Start: `cgroup` Permission Denied

libvirt's cgroups policy is blocking QEMU from opening `/dev/kvmfr0`. Confirm
the device is in `cgroup_device_acl` in `/etc/libvirt/qemu.conf` and that
`libvirtd` was restarted afterward (Phase 1.6).

### Looking Glass Reports Wrong Memory Size

The `size` value in the `qemu:commandline` JSON block does not match
`static_size_mb` in `/etc/modprobe.d/kvmfr.conf`. Both must agree. Recalculate
from the table in Phase 1.2 and update both files, then reload the module and
restart the VM.

### xfreerdp3: "Command Not Found"

The Arch `freerdp` package ≥ 3.4.0-5 uses versioned binary names. The correct
binary is `xfreerdp3`, not `xfreerdp`. Confirm:

```bash
which xfreerdp3
# Expected: /usr/bin/xfreerdp3
```

If the command is missing entirely, confirm `freerdp` (not `freerdp2`) is
installed: `pacman -Q freerdp`.

### KVMFR DKMS Fails to Build After Kernel Upgrade

On kernels ≥ 6.13, the KVMFR module requires two additional lines in `kvmfr.c`
that may not be present in older snapshots of `looking-glass-module-dkms-git`.
Update the AUR package first:

```bash
paru -Syu looking-glass-module-dkms-git
```

If the build still fails, check the AUR comments for
`looking-glass-module-dkms-git` — the maintainer typically publishes patches
for new kernel API changes within days of a kernel release.

---

## Appendix: Technical Reference

### Full Pipeline Component Summary

| Component | Location | Role | Failure Symptom |
|---|---|---|---|
| **KVMFR module** | Host kernel (`/dev/kvmfr0`) | DMA frame relay bus between guest GPU and host | `crw` not present; LG fails to open device |
| **`/etc/modprobe.d/kvmfr.conf`** | Host | Configures IVSHMEM size at module load | Module loads but `/dev/kvmfr0` is wrong size |
| **`/etc/udev/rules.d/70-kvmfr.rules`** | Host | Grants `kvm` group + seat user access | Permission denied when LG client opens device |
| **`cgroup_device_acl`** | `/etc/libvirt/qemu.conf` | Allows QEMU to open the char device | VM fails to start with cgroup policy error |
| **`qemu:commandline` block** | libvirt XML | Passes KVMFR device to QEMU as IVSHMEM | LG host in guest cannot find IVSHMEM PCI device |
| **VDD** | Windows guest | Provides NVIDIA GPU with a virtual monitor | GPU goes idle; no frames captured (Code 43) |
| **LG Host App** | Windows guest | Captures NVIDIA framebuffer → KVMFR | Black screen; no frames in shared memory |
| **`client.ini`** | `~/.config/looking-glass/` | Configures client behaviour persistently | Wrong escape key; connects to wrong device path |
| **`xfreerdp3`** | Host (`/usr/bin/xfreerdp3`) | RDP rescue bridge for Windows config | Cannot access Windows when emulated display is off |

### Memory Size Quick Reference

| `static_size_mb` | `qemu:commandline 'size'` | Max SDR resolution |
|---|---|---|
| 32 | 33554432 | 1080p / 1200p |
| 64 | 67108864 | 1440p |
| **128** | **134217728** | **4K (recommended default)** |
| 256 | 268435456 | 4K HDR |

### Escape Key Linux Input Event Codes (selected)

Run `looking-glass-client input:escapeKey=help` for the full list at any time.

| Key | Code |
|---|---|
| Scroll Lock | 70 |
| Right Control | 97 |
| Right Alt | 100 |
| Right Shift | 54 |
| Caps Lock | 58 |
| F12 | 88 |
