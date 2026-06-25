<#
.SYNOPSIS
    Dusky Windows Guest SSH Auto-Setup Utility
    Author: Antigravity Pair Programmer
    Description: Installs, configures, and secures the OpenSSH Server on Windows 10/11 VMs.
    Requirements: Run as Administrator in PowerShell.
#>

# 1. Enforce Administrator Privileges
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run as an Administrator. Please reopen PowerShell as Administrator."
    Exit 1
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   Dusky Windows SSH Auto-Setup Utility   " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 2. Check and Install OpenSSH Server Capability
Write-Host "`n[1/6] Checking OpenSSH Server installation status..." -ForegroundColor Yellow
$sshService = Get-WindowsCapability -Online -Name OpenSSH.Server*

if ($sshService.State -ne "Installed") {
    Write-Host "OpenSSH Server is not installed. Installing via DISM (shows progress)..." -ForegroundColor Cyan
    try {
        $dismResult = & dism /online /add-capability /capabilityname:OpenSSH.Server~~~~0.0.1.0 /quiet 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "DISM quiet install failed (code $LASTEXITCODE), retrying without /quiet..." -ForegroundColor Yellow
            $dismResult = & dism /online /add-capability /capabilityname:OpenSSH.Server~~~~0.0.1.0 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "DISM returned exit code $LASTEXITCODE"
            }
        }
        Write-Host "[OK] OpenSSH Server installed successfully." -ForegroundColor Green
    } catch {
        Write-Error "Failed to install OpenSSH Server: $_"
        Exit 1
    }
} else {
    Write-Host "[OK] OpenSSH Server capability is already installed." -ForegroundColor Green
}

# 3. Configure and Start SSHD Service
Write-Host "`n[2/6] Configuring SSH service startup..." -ForegroundColor Yellow
try {
    # Set SSH service to Automatic
    Set-Service -Name sshd -StartupType Automatic -ErrorAction Stop
    # Start the service if not running
    if ((Get-Service -Name sshd).Status -ne "Running") {
        Start-Service sshd -ErrorAction Stop
    }
    Write-Host "[OK] SSH service (sshd) set to Automatic and running." -ForegroundColor Green
} catch {
    Write-Error "Failed to configure SSH service: $_"
    Exit 1
}

# 4. Enforce Firewall Rule
Write-Host "`n[3/6] Checking firewall rules for port 22..." -ForegroundColor Yellow
$ruleName = "OpenSSH-Server-In-TCP"
$rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue

if ($rule) {
    try {
        Enable-NetFirewallRule -Name $ruleName -ErrorAction Stop
        Write-Host "[OK] Enabled default OpenSSH inbound firewall rule." -ForegroundColor Green
    } catch {
        Write-Error "Failed to enable inbound firewall rule: $_"
    }
} else {
    Write-Host "Default rule not found. Creating a custom inbound firewall rule..." -ForegroundColor Cyan
    try {
        New-NetFirewallRule -Name $ruleName -DisplayName "OpenSSH SSH Server (Inbound)" -Description "Inbound rule for OpenSSH Server (TCP port 22)" -Enabled True -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction Stop
        Write-Host "[OK] Created and enabled custom inbound firewall rule for port 22." -ForegroundColor Green
    } catch {
        Write-Error "Failed to create firewall rule: $_"
    }
}

# 5. Set Password for Current User
Write-Host "`n[4/6] Setting password for user '$env:USERNAME'..." -ForegroundColor Yellow
$securePassword = Read-Host "Enter a password for user '$env:USERNAME' (used for SSH login)" -AsSecureString
$confirmPassword = Read-Host "Confirm password" -AsSecureString

# Convert secure strings to plain text for comparison
$BSTR1 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$BSTR2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirmPassword)
$plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR1)
$plainConfirm = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR2)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR1)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR2)

if ($plainPassword -ne $plainConfirm) {
    Write-Error "Passwords do not match. Exiting."
    Exit 1
}

if ($plainPassword.Length -eq 0) {
    Write-Error "Password cannot be empty. Exiting."
    Exit 1
}

try {
    Set-LocalUser -Name $env:USERNAME -Password $securePassword -ErrorAction Stop
    Write-Host "[OK] Password set for user '$env:USERNAME'." -ForegroundColor Green
} catch {
    Write-Error "Failed to set password: $_"
    Exit 1
}

# 6. Configure sshd_config
Write-Host "`n[5/6] Tuning SSH configurations..." -ForegroundColor Yellow
$sshdConfigPath = "C:\ProgramData\ssh\sshd_config"

if (Test-Path $sshdConfigPath) {
    Write-Host "Ensuring PasswordAuthentication and PubkeyAuthentication are enabled..." -ForegroundColor Cyan
    $configContent = Get-Content $sshdConfigPath

    # Ensure PermitEmptyPasswords is no (safe default)
    if ($configContent -match "^#?PermitEmptyPasswords\s+") {
        $configContent = $configContent -replace "^#?PermitEmptyPasswords\s+\w+", "PermitEmptyPasswords no"
    } else {
        $configContent += "`nPermitEmptyPasswords no"
    }

    # Ensure PasswordAuthentication is yes
    if ($configContent -match "^#?PasswordAuthentication\s+") {
        $configContent = $configContent -replace "^#?PasswordAuthentication\s+\w+", "PasswordAuthentication yes"
    } else {
        $configContent += "`nPasswordAuthentication yes"
    }

    # Ensure PubkeyAuthentication is yes
    if ($configContent -match "^#?PubkeyAuthentication\s+") {
        $configContent = $configContent -replace "^#?PubkeyAuthentication\s+\w+", "PubkeyAuthentication yes"
    } else {
        $configContent += "`nPubkeyAuthentication yes"
    }

    # Save the updated configuration
    $configContent | Set-Content $sshdConfigPath -Force
    Write-Host "[OK] sshd_config tuned for secure password and key-based auth." -ForegroundColor Green
} else {
    Write-Warning "sshd_config not found at $sshdConfigPath. Skipping configuration tuning."
}

Write-Host "Setting PowerShell as the default SSH shell..." -ForegroundColor Cyan
try {
    $sshKeyPath = "HKLM:\SOFTWARE\OpenSSH"
    if (-not (Test-Path $sshKeyPath)) {
        New-Item -Path "HKLM:\SOFTWARE" -Name "OpenSSH" -Force | Out-Null
    }
    New-ItemProperty -Path $sshKeyPath -Name "DefaultShell" -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
    Write-Host "[OK] PowerShell set as the default SSH shell." -ForegroundColor Green
} catch {
    Write-Warning "Failed to set default SSH shell: $_"
}

# 7. Deploy authorized_keys for admin users
Write-Host "`n[6/6] Setting up authorized_keys for SSH public key authentication..." -ForegroundColor Yellow
$authKeysPath = "C:\ProgramData\ssh\administrators_authorized_keys"
$pubKey = Read-Host "Paste your host machine's SSH public key (e.g. from ~/.ssh/id_rsa.pub) or leave blank to skip"

if ($pubKey.Trim().Length -gt 0) {
    try {
        # Ensure the ssh directory exists
        $sshDir = "C:\ProgramData\ssh"
        if (-not (Test-Path $sshDir)) {
            New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
        }

        # Write the public key
        $pubKey.Trim() | Set-Content $authKeysPath -Force

        # Set proper ACLs: only SYSTEM and Administrators get read access
        icacls $authKeysPath /inheritance:r /grant "SYSTEM:(R)" /grant "BUILTIN\Administrators:(R)" | Out-Null

        Write-Host "[OK] Public key deployed to $authKeysPath with locked-down ACLs." -ForegroundColor Green
    } catch {
        Write-Error "Failed to deploy authorized_keys: $_"
    }
} else {
    Write-Host "[SKIP] No public key provided. You can manually add keys to $authKeysPath later." -ForegroundColor Yellow
}

# 8. Restart SSHD to Apply Settings
Write-Host "`nRestarting SSH service to apply configurations..." -ForegroundColor Yellow
try {
    Restart-Service sshd -ErrorAction Stop
    Write-Host "[OK] SSH service restarted successfully." -ForegroundColor Green
} catch {
    Write-Error "Failed to restart SSH service: $_"
    Exit 1
}

# 9. Summary & Diagnostics
$ipAddresses = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" }).IPAddress
Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "   SSH SETUP COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "You can now connect to this VM from the host using:" -ForegroundColor Cyan
foreach ($ip in $ipAddresses) {
    Write-Host "  ssh $env:USERNAME@$ip" -ForegroundColor Yellow
}
Write-Host "==========================================" -ForegroundColor Green
