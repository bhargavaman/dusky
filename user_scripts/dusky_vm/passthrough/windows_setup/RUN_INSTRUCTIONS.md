# Running setup_ssh.ps1 inside the VM

To configure OpenSSH on the guest Windows VM:

1. Open **PowerShell** as **Administrator** inside the Windows VM.
2. Copy and paste the following single command to execute the script from the shared VirtIO-FS drive (`Z:`):
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force; & "Z:\windows_setup\setup_ssh.ps1"
   ```
   *(Or if you copied it to the local C: drive, run: `Set-ExecutionPolicy Bypass -Scope Process -Force; & "C:\setup_ssh.ps1"`)*
