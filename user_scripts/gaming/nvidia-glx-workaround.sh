#!/usr/bin/env bash
#
# nvidia-glx-workaround_golden.sh
# Forces Mesa drivers and prevents NVIDIA GLX/EGL driver interference.
# High-reliability version with robust multilib compilation, fallback paths,
# and complete libglvnd environment overrides.

set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "Usage: $(basename "$0") <command> [args...]" >&2
    exit 1
fi

# 1. Native libglvnd Enforcements
export __GLX_VENDOR_LIBRARY_NAME="mesa"
export __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json"
export __NV_PRIME_RENDER_OFFLOAD=0
unset DRI_PRIME 2>/dev/null || true

# 2. Stub Interception (Multilib-Aware & Resilient)
STUB_BASE="${XDG_CACHE_HOME:-$HOME/.cache}/nvidia-glx-workaround"
STUB_64="$STUB_BASE/64"
STUB_32="$STUB_BASE/32"
TARGET_LIBS=(libGLX_nvidia.so.0 libEGL_nvidia.so.0)

STUB_PATH=""

build_stub() {
    local arch_name="$1"
    local out_dir="$2"
    local gcc_flag="$3"
    local fallback_lib="$4"

    mkdir -p "$out_dir"
    local build_success=0

    # Attempt 1: Compile custom C stub (safest for return values)
    if command -v gcc >/dev/null 2>&1; then
        local tmp_src
        tmp_src=$(mktemp --suffix=.c)
        
        cat > "$tmp_src" << 'STUBEOF'
void* glXGetClientString(void *d, int n) { return (void*)0; }
void* glXQueryServerString(void *d, int s, int n) { return (void*)0; }
void* glXGetScreenSpec(void *d, int s, const char *t) { return (void*)0; }
void* glXGetProcAddress(const char *p) { return (void*)0; }
void* glXGetProcAddressARB(const char *p) { return (void*)0; }
void* eglGetProcAddress(const char *p) { return (void*)0; }
const char* eglQueryString(void *d, int n) { return (void*)0; }
STUBEOF
        
        local all_libs_compiled=1
        for lib in "${TARGET_LIBS[@]}"; do
            local out_file="$out_dir/$lib"
            if [ ! -s "$out_file" ]; then
                if ! gcc -x c "$gcc_flag" -shared -fPIC -O2 -o "$out_file" "$tmp_src" 2>/dev/null; then
                    all_libs_compiled=0
                    break
                fi
            fi
        done
        
        rm -f "$tmp_src"
        if [ "$all_libs_compiled" -eq 1 ]; then
            return 0
        else
            # Clean up any partial files from this failed compiler run
            for lib in "${TARGET_LIBS[@]}"; do
                rm -f "$out_dir/$lib"
            done
        fi
    fi

    # Attempt 2: Zero-dependency Symlink Fallback
    if [ -f "$fallback_lib" ]; then
        for lib in "${TARGET_LIBS[@]}"; do
            local out_file="$out_dir/$lib"
            if [ ! -s "$out_file" ]; then
                ln -sf "$fallback_lib" "$out_file"
            fi
        done
        return 0
    fi

    return 1
}

# Build 64-bit stub (always available via Arch's /usr/lib)
if build_stub "64-bit" "$STUB_64" "-m64" "/usr/lib/libm.so.6"; then
    STUB_PATH="$STUB_64"
fi

# Build 32-bit stub (conditional on Arch's lib32-glibc presence)
if [ -d "/usr/lib32" ]; then
    if build_stub "32-bit" "$STUB_32" "-m32" "/usr/lib32/libm.so.6"; then
        STUB_PATH="${STUB_PATH:+$STUB_PATH:}$STUB_32"
    fi
fi

# 3. Inject stubs into the library path.
if [ -n "$STUB_PATH" ]; then
    export LD_LIBRARY_PATH="$STUB_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$@"
