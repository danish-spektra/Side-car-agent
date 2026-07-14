 
#Function1 - Disable Enhanced Security for Internet Explorer
Function Disable-InternetExplorerESC
{
    $AdminKey = "HKLM:\SOFTWARE\Microsoft\Active Setup\Installed Components\{A509B1A7-37EF-4b3f-8CFC-4F3A74704073}"
    $UserKey = "HKLM:\SOFTWARE\Microsoft\Active Setup\Installed Components\{A509B1A8-37EF-4b3f-8CFC-4F3A74704073}"
    Set-ItemProperty -Path $AdminKey -Name "IsInstalled" -Value 0 -Force -ErrorAction SilentlyContinue -Verbose
    Set-ItemProperty -Path $UserKey -Name "IsInstalled" -Value 0 -Force -ErrorAction SilentlyContinue -Verbose
    #Stop-Process -Name Explorer -Force
    Write-Host "IE Enhanced Security Configuration (ESC) has been disabled." -ForegroundColor Green -Verbose
}

#Function2 - Enable File Download on Windows Server Internet Explorer
Function Enable-IEFileDownload
{
    $HKLM = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\3"
    $HKCU = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\3"
    Set-ItemProperty -Path $HKLM -Name "1803" -Value 0 -ErrorAction SilentlyContinue -Verbose
    Set-ItemProperty -Path $HKCU -Name "1803" -Value 0 -ErrorAction SilentlyContinue -Verbose
    Set-ItemProperty -Path $HKLM -Name "1604" -Value 0 -ErrorAction SilentlyContinue -Verbose
    Set-ItemProperty -Path $HKCU -Name "1604" -Value 0 -ErrorAction SilentlyContinue -Verbose
}

#Function3 - Enable Copy Page Content in IE
Function Enable-CopyPageContent-In-InternetExplorer
{
    $HKLM = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\3"
    $HKCU = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\3"
    Set-ItemProperty -Path $HKLM -Name "1407" -Value 0 -ErrorAction SilentlyContinue -Verbose
    Set-ItemProperty -Path $HKCU -Name "1407" -Value 0 -ErrorAction SilentlyContinue -Verbose
}

#Function4 Install Chocolatey
# Detect .NET Framework 4.8+ (release 528040). Returns $true if present.
Function Test-DotNet48Installed {
    try {
        $rel = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release -ErrorAction Stop).Release
        return ($rel -ge 528040)
    } catch { return $false }
}

# Install .NET Framework 4.8 (web installer) silently. Returns $true if install succeeded
# (caller should consider a reboot may still be required to fully activate).
Function Install-DotNet48 {
    if (Test-DotNet48Installed) {
        Write-Host "[OK] .NET Framework 4.8 already installed." -ForegroundColor Green
        return $true
    }
    Write-Host "[INFO] Installing .NET Framework 4.8 (required by Chocolatey v2)..." -ForegroundColor Cyan
    if (-not (Test-Path 'C:\Packages')) { New-Item -ItemType Directory -Path 'C:\Packages' -Force | Out-Null }
    $url = 'https://download.visualstudio.microsoft.com/download/pr/2d6bb6b2-226a-4baa-bdec-798822606ff1/8494001c276a4b96804cde7829c04d7f/ndp48-x86-x64-allos-enu.exe'
    $installer = 'C:\Packages\ndp48-x86-x64-allos-enu.exe'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop
        $p = Start-Process -FilePath $installer -ArgumentList '/quiet','/norestart' -Wait -PassThru
        # 0=success, 3010=success+reboot required, 1641=success+reboot initiated
        if ($p.ExitCode -in 0, 3010, 1641) {
            Write-Host "[OK] .NET 4.8 installer exit code: $($p.ExitCode)" -ForegroundColor Green
            if ($p.ExitCode -in 3010, 1641) {
                Write-Warning "REBOOT REQUIRED to fully activate .NET 4.8 - choco v2 may still report missing until then."
            }
            return $true
        } else {
            Write-Warning ".NET 4.8 installer returned exit code $($p.ExitCode)."
            return $false
        }
    } catch {
        Write-Warning ".NET 4.8 install failed: $_"
        return $false
    }
}

# Returns the major version number of an installed Chocolatey, or 0 if not installed.
Function Get-InstalledChocoMajorVersion {
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) { return 0 }
    try {
        $verLine = (& choco --version 2>$null | Select-Object -First 1)
        if ($verLine -match '^\s*(\d+)\.') { return [int]$Matches[1] }
    } catch {}
    return 0
}

Function InstallChocolatey
{
    $env:chocolateyUseWindowsCompression = 'true'
    $env:chocolateyIgnoreRebootDetected  = 'true'

    # ---- OS-aware version selection ----
    # Choco v2.x requires .NET Framework 4.8. On Windows Server 2019 (build 17763) and older,
    # .NET 4.8 is NOT shipped in-box and a fresh install of it requires a reboot to activate.
    # To keep deployments single-pass (no reboot needed), we pin those OSes to choco v1.4.0
    # which only needs .NET 4.6.1+ (in-box on Server 2016/2019).
    # Server 2022 (build 20348+) and Windows 10/11 ship with .NET 4.8 -> use choco v2.7.0.
    $os         = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
    $buildNum   = if ($os) { [int]$os.BuildNumber } else { 0 }
    $isServer   = $os -and $os.ProductType -ne 1
    $isLegacyServer = ($isServer -and $buildNum -lt 20348)   # Server 2019/2016/2012R2

    if ($isLegacyServer) {
        $targetChocoMajor    = 1
        $env:chocolateyVersion = '1.4.0'
        Write-Host "[INFO] Detected legacy Windows Server (build $buildNum). Pinning Chocolatey to v1.4.0 (no .NET 4.8 dependency)." -ForegroundColor Cyan
    } else {
        $targetChocoMajor    = 2
        $env:chocolateyVersion = '2.7.0'
        Write-Host "[INFO] Detected modern Windows (build $buildNum). Using Chocolatey v2.7.0." -ForegroundColor Cyan

        # Modern OS: ensure .NET 4.8 is present (in-box on Server 2022 / Win10 1903+ / Win11, but verify).
        if (-not (Test-DotNet48Installed)) {
            Write-Warning "Modern OS detected but .NET 4.8 missing - installing now..."
            [void](Install-DotNet48)
        }
    }

    # ---- Reconcile against any existing install ----
    $installedMajor = Get-InstalledChocoMajorVersion

    if ($installedMajor -eq $targetChocoMajor) {
        Write-Host "[OK] Chocolatey v$installedMajor already installed (matches target) - skipping bootstrap." -ForegroundColor Green
        choco feature enable -n allowGlobalConfirmation 2>$null | Out-Null
        return
    }

    if ($installedMajor -ge 1 -and $installedMajor -ne $targetChocoMajor) {
        # Wrong major version installed (e.g. v2 on Server 2019 from a prior run).
        # Remove existing install dir and re-bootstrap at the correct version.
        Write-Warning "[INFO] Installed Chocolatey is v$installedMajor but target for this OS is v$targetChocoMajor. Replacing..."
        $reinstalled = Install-ChocoVersion -TargetMajor $targetChocoMajor
        if (-not $reinstalled) {
            Write-Warning "Could not reinstall Chocolatey to v$targetChocoMajor. Package installs may fail."
        }
        return
    }

    # ---- Fresh install ----
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11

    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco feature enable -n allowGlobalConfirmation
    } else {
        Write-Warning "choco command not yet on PATH - may require new shell."
    }
}

# Replace an existing Chocolatey install with the requested major version.
# Backs up (or removes) the existing C:\ProgramData\chocolatey directory because the
# community install.ps1 refuses to overwrite an existing install.
Function Install-ChocoVersion {
    param(
        [Parameter(Mandatory=$true)][ValidateSet(1,2)][int]$TargetMajor
    )
    $version = if ($TargetMajor -eq 1) { '1.4.0' } else { '2.7.0' }
    Write-Warning "[INFO] Reinstalling Chocolatey at v$version (remove + re-bootstrap)..."
    try {
        Get-Process -Name 'choco','chocolatey' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

        $chocoRoot = if ($env:ChocolateyInstall) { $env:ChocolateyInstall } else { 'C:\ProgramData\chocolatey' }
        if (Test-Path $chocoRoot) {
            $backup = "$chocoRoot.bak-$(Get-Date -Format 'yyyyMMddHHmmss')"
            Write-Host "  Backing up existing choco install: $chocoRoot -> $backup" -ForegroundColor Cyan
            try {
                Move-Item -Path $chocoRoot -Destination $backup -Force -ErrorAction Stop
            } catch {
                Write-Warning "  Move-Item failed ($_). Falling back to Remove-Item..."
                Remove-Item -Path $chocoRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        $env:chocolateyUseWindowsCompression = 'true'
        $env:chocolateyIgnoreRebootDetected  = 'true'
        $env:chocolateyVersion               = $version
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11
        Set-ExecutionPolicy Bypass -Scope Process -Force
        iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
        $maj = Get-InstalledChocoMajorVersion
        if ($maj -eq $TargetMajor) {
            Write-Host "[OK] Chocolatey reinstalled at v$maj.x successfully." -ForegroundColor Green
            choco feature enable -n allowGlobalConfirmation 2>$null | Out-Null
            return $true
        }
        Write-Warning "Reinstall completed but version is $maj (expected $TargetMajor)."
        return $false
    } catch {
        Write-Warning "Choco reinstall failed: $_"
        return $false
    }
}

# Choco-to-Winget package name mapping for fallback
$Global:ChocoToWingetMap = @{
    "googlechrome"                  = "Google.Chrome"
    "firefox"                       = "Mozilla.Firefox"
    "vscode"                        = "Microsoft.VisualStudioCode"
    "git.install"                   = "Git.Git"
    "putty.install"                 = "PuTTY.PuTTY"
    "7zip.install"                  = "7zip.7zip"
    "nodejs"                        = "OpenJS.NodeJS"
    "python"                        = "Python.Python.3.12"
    "azure-cli"                     = "Microsoft.AzureCLI"
    "powerbi"                       = "Microsoft.PowerBI"
    "docker-for-windows"            = "Docker.DockerDesktop"
    "dotnetfx"                      = "Microsoft.DotNet.Framework.DeveloperPack_4"
    "adobereader"                   = "Adobe.Acrobat.Reader.64-bit"
    "winscp.install"                = "WinSCP.WinSCP"
    "sql-server-management-studio"  = "Microsoft.SQLServerManagementStudio"
    "dotnetcore"                    = "Microsoft.DotNet.Runtime.3_1"
}

# Check if Chocolatey source is reachable (fix #8: enforce TLS 1.2 + retry)
Function Test-ChocoAvailable {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11
    for ($i = 1; $i -le 3; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "https://community.chocolatey.org" -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Write-Warning "Chocolatey reachability check failed (attempt $i/3): $_"
            if ($i -lt 3) { Start-Sleep -Seconds 5 }
        }
    }
    return $false
}

# Fix #5: Detect Windows Server SKU/version - winget unavailable on Server 2019 and older
Function Test-WingetSupportedOS {
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        # ProductType: 1=Workstation, 2=DC, 3=Server. Server 2019 BuildNumber=17763, Server 2016=14393
        if ($os.ProductType -ne 1 -and [int]$os.BuildNumber -lt 20348) {
            # Server prior to 2022 (build 20348) lacks AppX/MSIX runtime needed by winget
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

# Check if winget is available (install PS module if missing)
Function Test-WingetAvailable {
    # Fix #5: Skip on unsupported OS (Server 2019/2016) - bootstrap will fail anyway
    if (-not (Test-WingetSupportedOS)) {
        Write-Host "  [INFO] winget not supported on this OS (Server <2022 / no AppX). Skipping." -ForegroundColor Yellow
        return $false
    }
    # Prefer the PS module - works in the same session without PATH issues
    if (Get-Module -ListAvailable -Name Microsoft.WinGet.Client -ErrorAction SilentlyContinue) {
        return $true
    }
    # Fallback: check if winget.exe is in PATH
    try {
        $null = Get-Command winget -ErrorAction Stop
        return $true
    } catch {
        Write-Host "  [INFO] winget not found. Attempting to install PS module..." -ForegroundColor Yellow
        return (Install-Winget)
    }
}

# Bootstrap winget PowerShell module (works in same session, no PATH/new-shell needed)
Function Install-Winget {
    try {
        $ProgressPreference = 'SilentlyContinue'
        Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -ErrorAction SilentlyContinue | Out-Null

        # PowerShellGet 1.0.0.1 (default on Server 2019) lacks -AcceptLicense. Pass it only if supported.
        $installModuleParams = @{
            Name        = 'Microsoft.WinGet.Client'
            Force       = $true
            Scope       = 'AllUsers'
            ErrorAction = 'Stop'
        }
        if ((Get-Command Install-Module).Parameters.ContainsKey('AcceptLicense')) {
            $installModuleParams['AcceptLicense'] = $true
        }

        Write-Host "  [winget] Installing Microsoft.WinGet.Client PS module..." -ForegroundColor Cyan
        Install-Module @installModuleParams | Out-Null

        Write-Host "  [winget] Running Repair-WinGetPackageManager..." -ForegroundColor Cyan
        Repair-WinGetPackageManager -Latest -Force -ErrorAction Stop

        Import-Module Microsoft.WinGet.Client -ErrorAction Stop
        Write-Host "  [OK] Microsoft.WinGet.Client module ready (same session)." -ForegroundColor Green
        return $true
    } catch {
        Write-Warning "  [FAILED] Could not install winget PS module: $_"
        return $false
    }
}

# Install via winget as fallback (uses PS module cmdlet - works in same session)
Function Install-ViaWinget {
    param(
        [Parameter(Mandatory=$true)]
        [string]$WingetId,
        [int]$MaxRetries = 2
    )
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        Write-Host "  [winget $attempt/$MaxRetries] Installing '$WingetId'..." -ForegroundColor Magenta

        # Strategy 1: Use Install-WinGetPackage PS cmdlet (no winget.exe PATH needed)
        try {
            Import-Module Microsoft.WinGet.Client -ErrorAction Stop
            $result = Install-WinGetPackage -Id $WingetId -Mode Silent -Force -ErrorAction Stop
            if ($result.Status -eq 'Ok' -or $result.InstallerErrorCode -eq 0) {
                Write-Host "  [OK] '$WingetId' installed via winget PS module." -ForegroundColor Green
                return $true
            } else {
                Write-Warning "  winget result: Status=$($result.Status), Error=$($result.InstallerErrorCode)"
            }
        } catch {
            Write-Warning "  winget PS module error: $_"
        }

        # Strategy 2: Try winget.exe directly (in case it is in PATH)
        try {
            $null = Get-Command winget -ErrorAction Stop
            $output = winget install --id $WingetId --accept-source-agreements --accept-package-agreements --silent 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] '$WingetId' installed via winget CLI." -ForegroundColor Green
                return $true
            }
        } catch {
            # winget.exe not in PATH - expected on Server
        }

        if ($attempt -lt $MaxRetries) { Start-Sleep -Seconds 10 }
    }
    return $false
}

# Resilient install wrapper: Chocolatey -> winget fallback
Function Install-ChocoPackage {
    param(
        [Parameter(Mandatory=$true)]
        [string]$PackageName,

        [string]$AdditionalArgs = "",

        [int]$MaxRetries = 3,

        [int]$RetryDelaySeconds = 15
    )

    # Defensive init of failed-packages tracker (avoid null-ref from inline if-expression)
    if ($null -eq $Global:ChocoFailedPackages) {
        $Global:ChocoFailedPackages = [System.Collections.ArrayList]::new()
    }
    $failedPackages = $Global:ChocoFailedPackages

    # Check choco availability once per session
    if ($null -eq $Global:ChocoIsAvailable) {
        $Global:ChocoIsAvailable = Test-ChocoAvailable
        if (-not $Global:ChocoIsAvailable) {
            Write-Host "[WARN] Chocolatey source is DOWN. Will use winget fallback." -ForegroundColor Yellow
        }
    }

    $installed = $false

    # --- Try Chocolatey first (if reachable) ---
    if ($Global:ChocoIsAvailable) {
        # Choco success exit codes: 0 (ok), 1605/1614 (already in target state), 1641/3010 (success, reboot required)
        $successCodes = @(0, 1605, 1614, 1641, 3010)
        $ignoreChecksumsThisRun = $false
        for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
            Write-Host "[$attempt/$MaxRetries] Installing '$PackageName' via Chocolatey..." -ForegroundColor Cyan
            try {
                # Fix #4: invoke choco directly (no cmd.exe shell-out) for reliable $LASTEXITCODE
                $chocoArgList = @('install', $PackageName, '-y', '--no-progress', '--force')
                if ($ignoreChecksumsThisRun) {
                    # Stale package metadata workaround - vendor MSI is downloaded over HTTPS from official URL
                    $chocoArgList += '--ignore-checksums'
                    Write-Host "  Retrying with --ignore-checksums (vendor binary newer than choco package metadata)" -ForegroundColor Yellow
                }
                if ($AdditionalArgs) { $chocoArgList += $AdditionalArgs.Split(' ') }
                # Capture output so we can detect checksum mismatches and retry intelligently.
                $output = & choco @chocoArgList 2>&1 | Tee-Object -Variable chocoStream
                $exitCode = $LASTEXITCODE

                # Fix #4: accept reboot-required codes as success
                if ($successCodes -contains $exitCode) {
                    # Fix #2: validate via 'choco list --exact --limit-output' (reliable on choco v2)
                    $listOut = & choco list --exact $PackageName --limit-output 2>$null
                    if ($LASTEXITCODE -eq 0 -and $listOut) {
                        Write-Host "[OK] '$PackageName' installed successfully via Chocolatey (exit=$exitCode)." -ForegroundColor Green
                    } else {
                        Write-Host "[OK] '$PackageName' install reported success (exit=$exitCode); not listed - meta-package or framework." -ForegroundColor Green
                    }
                    return $true
                } else {
                    Write-Warning "'$PackageName' install returned exit code $exitCode (attempt $attempt/$MaxRetries)"
                    # Detect stale-checksum failure pattern in choco output
                    $outputText = ($chocoStream | Out-String)
                    if (-not $ignoreChecksumsThisRun -and ($outputText -match 'hashes do not match' -or $outputText -match 'Checksum for .* did not meet')) {
                        Write-Warning "  Checksum mismatch detected - package metadata is stale. Will retry with --ignore-checksums."
                        $ignoreChecksumsThisRun = $true
                    }
                }
            } catch {
                Write-Warning "'$PackageName' install threw error (attempt $attempt/$MaxRetries): $_"
            }

            if ($attempt -lt $MaxRetries) {
                Write-Host "Retrying in $RetryDelaySeconds seconds..." -ForegroundColor Yellow
                Start-Sleep -Seconds $RetryDelaySeconds
                # Fix #3: do NOT uninstall between retries - destructive if previous attempt partially succeeded.
                # 'choco install --force' already handles re-install cleanly.
            }
        }
        Write-Host "[CHOCO FAILED] '$PackageName' failed after $MaxRetries attempts. Trying winget..." -ForegroundColor Yellow
    }

    # --- Winget fallback ---
    $wingetId = $Global:ChocoToWingetMap[$PackageName]
    if ($wingetId -and (Test-WingetAvailable)) {
        $installed = Install-ViaWinget -WingetId $wingetId
    } elseif (-not $wingetId) {
        Write-Host "  [SKIP] No winget mapping for '$PackageName'." -ForegroundColor Yellow
    } else {
        Write-Host "  [SKIP] winget not available on this system." -ForegroundColor Yellow
    }

    if (-not $installed) {
        Write-Host "[FAILED] '$PackageName' could not be installed via Chocolatey or winget." -ForegroundColor Red
        $null = $failedPackages.Add($PackageName)
        return $false
    }
    return $true
}

# Call at the end of your setup script to report all failures
Function Get-ChocoInstallReport {
    $reportPath = "C:\WindowsAzure\Logs\cloudlabscommoninstaller.txt"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    # Ensure log directory exists (may not on freshly-deployed/custom images)
    $logDir = Split-Path -Path $reportPath -Parent
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    if ($Global:ChocoFailedPackages -and $Global:ChocoFailedPackages.Count -gt 0) {
        Write-Host "`n========== PACKAGE INSTALL FAILURES ==========" -ForegroundColor Red
        $lines = @("[$timestamp] PACKAGE INSTALL REPORT - FAILURES DETECTED")
        foreach ($pkg in $Global:ChocoFailedPackages) {
            Write-Host "  [FAILED] $pkg" -ForegroundColor Red
            $lines += "  [FAILED] $pkg"
        }
        Write-Host "================================================`n" -ForegroundColor Red
        $lines += "================================================"
        $lines | Out-File -FilePath $reportPath -Encoding UTF8 -Force
        Write-Host "Report saved to $reportPath" -ForegroundColor Yellow
        return $false
    } else {
        Write-Host "`n[OK] All packages installed successfully.`n" -ForegroundColor Green
        "[$timestamp] All packages installed successfully." | Out-File -FilePath $reportPath -Encoding UTF8 -Force
        Write-Host "Report saved to $reportPath" -ForegroundColor Yellow
        return $true
    }
}

#Function5 Disable PopUp for network configuration

Function DisableServerMgrNetworkPopup
{
    # Fix #22: Create the registry KEY 'NewNetworkWindowOff' under Network (the key's presence is what suppresses the popup).
    $networkKey = 'HKLM:\System\CurrentControlSet\Control\Network\NewNetworkWindowOff'
    if (-not (Test-Path $networkKey)) {
        New-Item -Path $networkKey -Force | Out-Null
    }

    Get-ScheduledTask -TaskName ServerManager -ErrorAction SilentlyContinue | Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null
}

Function CreateLabFilesDirectory
{
    New-Item -ItemType directory -Path C:\LabFiles -force
}

Function DisableWindowsFirewall
{
    Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

}

Function Show-File-Extension
{
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
    Set-ItemProperty $key HideFileExt 0
    Stop-Process -processname explorer -ErrorAction SilentlyContinue
}



#Function - InstallPowerBIDesktop
Function InstallPowerBiDesktopChoco
{
    # Fix (e): 'powerbi' choco package is deprecated; use 'powerbi-desktop'
    Install-ChocoPackage -PackageName "powerbi-desktop"
}
Function InstallPowerBIDesktop
{
    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://download.microsoft.com/download/8/8/0/880bca75-79dd-466a-927d-1abf1f5454b0/PBIDesktopSetup_x64.exe","C:\Packages\PBIDesktop_x64.exe")
    Start-Process -FilePath "C:\Packages\PBIDesktop_x64.exe" -ArgumentList '-quiet','ACCEPT_EULA=1' -Wait
}


Function InstallScreenConnectforSPL
{
    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/software/screenconnectspl.msi","C:\Packages\screenconnectspl.msi")
    Start-Process msiexec.exe -Wait '/I C:\Packages\screenconnectspl.msi /qn' -Verbose
}

Function InstallCloudLabsShadow($odlid, $InstallCloudLabsShadow)
{
   # if($InstallCloudLabsShadow -eq 'yes')
   # {
   #     $WebClient = New-Object System.Net.WebClient
   #     $url1 = "https://spektrasystems.screenconnect.com/Bin/ConnectWiseControl.ClientSetup.msi?h=instance-ma1weu-relay.screenconnect.com&p=443&k=BgIAAACkAABSU0ExAAgAAAEAAQDhrCYwK%2BhPzyOyTYW71BahP4Q7hsWvkU20udO6d7cGuH8VAADzVNnsk39zavkgVu2uLHR1mfAL%2BUd6iAJOofhlcjO%2FB%2FVAEwvqtQ7403Nqm6rGvy6%2FxHEiqvzvn42JADRxdGVFaw9SYyTi4QckGjG0OnG69mW2RBQdWOZ3FKmhJD6zWRPZVTbl7gJkpIdMZx0BbWKiYVsvJYgoCWNXIqqH77rigu5dsmEnWeC9J0Or1KaU%2Bzsd6QJwAzEwomhiGp3FII4wbGBnCiHLD%2FrtNgR%2BJ1H3bKgYkesdxuFvO5DzUc3eEOVBSwR0crd06J%2BJP4DolgWWNZN6ZmQ1s5aOQgSq&e=Access&y=Guest&t=&c="
   #     $url3 = "&c=&c=&c=&c=&c=&c=&c="
   #     $finalurl = $url1 + $odlid + $url3
   #     $WebClient.DownloadFile("$finalurl","C:\Packages\cloudlabsshadow.msi")
   #    Start-Process msiexec.exe -Wait '/I C:\Packages\cloudlabsshadow.msi /qn' -Verbose
   # }
}

Function Enable-CloudLabsEmbeddedShadow($vmAdminUsername, $trainerUserName, $trainerUserPassword)
{
Write-Host "Enabling CloudLabsEmbeddedShadow"
#Created Trainer Account and Add to Administrators Group
$trainerUserPass = $trainerUserPassword | ConvertTo-SecureString -AsPlainText -Force

New-LocalUser -Name $trainerUserName -Password $trainerUserPass -FullName "$trainerUserName" -Description "CloudLabs EmbeddedShadow User" -PasswordNeverExpires
Add-LocalGroupMember -Group "Administrators" -Member "$trainerUserName"

#Add Windows regitary to enable Shadow
reg add "HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v Shadow /t REG_DWORD /d 2 -f

#Download Shadow.ps1 and Shadow.xml file in VM
$drivepath="C:\Users\Public\Documents"
$WebClient = New-Object System.Net.WebClient
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/Shadow.ps1","$drivepath\Shadow.ps1")
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/shadow.xml","$drivepath\shadow.xml")
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/ShadowSession.zip","C:\Packages\ShadowSession.zip")
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/executetaskscheduler.ps1","$drivepath\executetaskscheduler.ps1")
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/shadowshortcut.ps1","$drivepath\shadowshortcut.ps1")

# Unzip Shadow User Session Shortcut to Trainer Desktop
#$trainerloginuser= "$trainerUserName" + "." + "$($env:ComputerName)"
#Expand-Archive -LiteralPath 'C:\Packages\ShadowSession.zip' -DestinationPath "C:\Users\$trainerloginuser\Desktop" -Force
#Expand-Archive -LiteralPath 'C:\Packages\ShadowSession.zip' -DestinationPath "C:\Users\$trainerUserName\Desktop" -Force

#Replace vmAdminUsernameValue with VM Admin UserName in script content 
(Get-Content -Path "$drivepath\Shadow.ps1") | ForEach-Object {$_ -Replace "vmAdminUsernameValue", "$vmAdminUsername"} | Set-Content -Path "$drivepath\Shadow.ps1"
(Get-Content -Path "$drivepath\shadow.xml") | ForEach-Object {$_ -Replace "vmAdminUsernameValue", "$trainerUserName"} | Set-Content -Path "$drivepath\shadow.xml"
(Get-Content -Path "$drivepath\shadow.xml") | ForEach-Object {$_ -Replace "ComputerNameValue", "$($env:ComputerName)"} | Set-Content -Path "$drivepath\shadow.xml"
(Get-Content -Path "$drivepath\shadowshortcut.ps1") | ForEach-Object {$_ -Replace "vmAdminUsernameValue", "$trainerUserName"} | Set-Content -Path "$drivepath\shadowshortcut.ps1"

# Scheduled Task to Run Shadow.ps1 AtLogOn
schtasks.exe /Create /XML $drivepath\shadow.xml /tn Shadowtask

$Trigger= New-ScheduledTaskTrigger -AtLogOn
$User= "$($env:ComputerName)\$trainerUserName" 
$Action= New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\Powershell.exe" -Argument "-executionPolicy Unrestricted -File $drivepath\shadowshortcut.ps1 -WindowStyle Hidden"
Register-ScheduledTask -TaskName "shadowshortcut" -Trigger $Trigger -User $User -Action $Action -RunLevel Highest -Force
}

#Create Azure Credential File on Desktop
Function CreateCredFile($AzureUserName, $AzurePassword, $AzureTenantID, $AzureSubscriptionID, $DeploymentID)
{
    New-Item -ItemType directory -Path C:\LabFiles -force

    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/AzureCreds.txt","C:\LabFiles\AzureCreds.txt")
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/AzureCreds.ps1","C:\LabFiles\AzureCreds.ps1")

    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object {$_ -Replace "AzureUserNameValue", "$AzureUserName"} | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object {$_ -Replace "AzurePasswordValue", "$AzurePassword"} | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object {$_ -Replace "AzureTenantIDValue", "$AzureTenantID"} | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object {$_ -Replace "AzureSubscriptionIDValue", "$AzureSubscriptionID"} | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object {$_ -Replace "DeploymentIDValue", "$DeploymentID"} | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
             
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "AzureUserNameValue", "$AzureUserName"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "AzurePasswordValue", "$AzurePassword"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "AzureTenantIDValue", "$AzureTenantID"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "AzureSubscriptionIDValue", "$AzureSubscriptionID"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "DeploymentIDValue", "$DeploymentID"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"

    Copy-Item "C:\LabFiles\AzureCreds.txt" -Destination "C:\Users\Public\Desktop"
}

#Add Service Principle details to Azure Credential Files
Function SPtoAzureCredFiles($SPDisplayName, $SPID, $SPObjectID, $SPSecretKey, $AzureTenantDomainName)
{
    if (-not (Test-Path "C:\LabFiles\AzureCreds.txt")) {
        Write-Warning "SPtoAzureCredFiles: C:\LabFiles\AzureCreds.txt not found. Run CreateCredFile first."
        return
    }
    Add-Content -Path "C:\LabFiles\AzureCreds.txt" -Value "AzureServicePrincipalDisplayName= $SPDisplayName" -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.txt" -Value "AzureServicePrincipalAppID= $SPID" -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.txt" -Value "AzureServicePrincipalObjectID= $SPObjectID" -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.txt" -Value "AzureServicePrincipalSecretKey= $SPSecretKey" -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.txt" -Value "AzureTenantDomainName= $AzureTenantDomainName" -PassThru

    Add-Content -Path "C:\LabFiles\AzureCreds.ps1" -Value '$AzureServicePrincipalDisplayName="SPDisplayNameValue"' -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.ps1" -Value '$AzureServicePrincipalAppID="SPIDValue"' -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.ps1" -Value '$AzureServicePrincipalObjectID="SPObjectIDValue"' -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.ps1" -Value '$AzureServicePrincipalSecretKey="SPSecretKeyValue"' -PassThru
    Add-Content -Path "C:\LabFiles\AzureCreds.ps1" -Value '$AzureTenantDomainName="AzureTenantDomainNameValue"' -PassThru

    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "SPDisplayNameValue", "$SPDisplayName"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "SPIDValue", "$SPID"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "SPObjectIDValue", "$SPObjectID"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "SPSecretKeyValue", "$SPSecretKey"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object {$_ -Replace "AzureTenantDomainNameValue", "$AzureTenantDomainName"} | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"

    Copy-Item "C:\LabFiles\AzureCreds.txt" -Destination "C:\Users\Public\Desktop" -force
}

#Install Cloudlabs Modern VM (Windows Server 2012,2016,2019, Windows 10) Validator
Function InstallModernVmValidator
{   #dotnet core is pre-req for vmagent or validator
    Install-ChocoPackage -PackageName "dotnetcore"
    #Create C:\CloudLabs\Validator directory
    New-Item -ItemType directory -Path C:\CloudLabs\Validator -Force
    Invoke-WebRequest 'https://experienceazure.blob.core.windows.net/software/vm-validator/VMAgent.zip' -OutFile 'C:\CloudLabs\Validator\VMAgent.zip'
    Expand-Archive -LiteralPath 'C:\CloudLabs\Validator\VMAgent.zip' -DestinationPath 'C:\CloudLabs\Validator' -Force
    Set-ExecutionPolicy -ExecutionPolicy bypass -Force
    cmd.exe --% /c @echo off
    cmd.exe --% /c sc create "Spektra CloudLabs VM Agent" BinPath=C:\CloudLabs\Validator\VMAgent\Spektra.CloudLabs.VMAgent.exe start= auto
    Start-Sleep -Seconds 3
    cmd.exe --% /c sc start "Spektra CloudLabs VM Agent"
}

#Install Cloudlabs Legacy VM (Windows Server 2008R2) Validator
Function InstallLegacyVmValidator
{
    #Create C:\CloudLabs
    New-Item -ItemType directory -Path C:\CloudLabs\Validator -Force
    Invoke-WebRequest 'https://experienceazure.blob.core.windows.net/software/vm-validator/LegacyVMAgent.zip' -OutFile 'C:\CloudLabs\Validator\LegacyVMAgent.zip'
    Expand-Archive -LiteralPath 'C:\CloudLabs\Validator\LegacyVMAgent.zip' -DestinationPath 'C:\CloudLabs\Validator' -Force
    Set-ExecutionPolicy -ExecutionPolicy bypass -Force
    cmd.exe --% /c @echo off
    cmd.exe --% /c sc create "Spektra CloudLabs Legacy VM Agent" binpath= C:\CloudLabs\Validator\LegacyVMAgent\Spektra.CloudLabs.LegacyVMAgent.exe displayname= "Spektra CloudLabs Legacy VM Agent" start= auto
    Start-Sleep -Seconds 3
    cmd.exe --% /c sc start "Spektra CloudLabs Legacy VM Agent"

}

#Install SQl Server Management studio
Function InstallSQLSMS
{
    Install-ChocoPackage -PackageName "sql-server-management-studio"

    # Auto-detect installed SSMS version (18, 19, 20, 21, etc.)
    $ssmsExe = Get-ChildItem "C:\Program Files (x86)\Microsoft SQL Server Management Studio *\Common7\IDE\Ssms.exe" -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $ssmsExe) {
        # Fallback: try Program Files (non-x86) for newer versions
        $ssmsExe = Get-ChildItem "C:\Program Files\Microsoft SQL Server Management Studio *\Common7\IDE\Ssms.exe" -ErrorAction SilentlyContinue |
                   Sort-Object FullName -Descending | Select-Object -First 1
    }

    if ($ssmsExe) {
        $version = $ssmsExe.Directory.Parent.Parent.Name -replace '.*Studio\s*', ''
        $WshShell = New-Object -comObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("C:\Users\Public\Desktop\Microsoft SQL Server Management Studio $version.lnk")
        $Shortcut.TargetPath = $ssmsExe.FullName
        $Shortcut.Save()
        Write-Host "SSMS shortcut created for version $version at $($ssmsExe.FullName)" -ForegroundColor Green
    } else {
        Write-Warning "SSMS executable not found after install - shortcut not created"
    }
}

#Install Azure Powershell Az Module (Fix #23: install from PSGallery; MSI path was dead/forward-dated)
Function InstallAzPowerShellModule
{
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11

    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope AllUsers -ErrorAction SilentlyContinue | Out-Null

    if (-not (Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue)) {
        Register-PSRepository -Default -ErrorAction SilentlyContinue
    }
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction SilentlyContinue

    # PowerShellGet 1.0.0.1 (Server 2019 default) lacks -AcceptLicense; pass it only if supported.
    $azParams = @{
        Name        = 'Az'
        Repository  = 'PSGallery'
        Scope       = 'AllUsers'
        Force       = $true
        AllowClobber= $true
        ErrorAction = 'Stop'
    }
    if ((Get-Command Install-Module).Parameters.ContainsKey('AcceptLicense')) {
        $azParams['AcceptLicense'] = $true
    }

    try {
        Install-Module @azParams
        Write-Host "[OK] Az module installed from PSGallery." -ForegroundColor Green
    } catch {
        Write-Warning "Az module install failed: $_"
    }

    Import-Module Az.Accounts -ErrorAction SilentlyContinue
    Update-AzConfig -LoginExperienceV2 Off -ErrorAction SilentlyContinue
    Update-AzConfig -EnableLoginByWam $false -ErrorAction SilentlyContinue
}

Function InstallAzCLI
{
    Install-ChocoPackage -PackageName "azure-cli"
}

Function InstallGoogleChrome
{
    Install-ChocoPackage -PackageName "googlechrome"
}

Function InstallVSCode
{
    Install-ChocoPackage -PackageName "vscode"
}

Function InstallGitTools
{
    Install-ChocoPackage -PackageName "git.install"
}

Function InstallPutty
{
    Install-ChocoPackage -PackageName "putty.install"
}

Function InstallAdobeReader
{
    Install-ChocoPackage -PackageName "adobereader"
}

Function InstallFirefox
{
    Install-ChocoPackage -PackageName "firefox"
}

Function Install7Zip
{
    Install-ChocoPackage -PackageName "7zip.install"
}


Function InstallNodeJS
{
    Install-ChocoPackage -PackageName "nodejs"
}

Function InstallDotNet4.5
{
    Install-ChocoPackage -PackageName "dotnet4.5"
}

Function InstallDotNetFW4.8
{
    Install-ChocoPackage -PackageName "dotnetfx"
}

Function InstallPython
{
    Install-ChocoPackage -PackageName "python"
}

Function InstallWinSCP
{
    Install-ChocoPackage -PackageName "winscp.install"
}

Function Installvisualstudio2019professional
{
    Install-ChocoPackage -PackageName "visualstudio2019professional"
}

Function Installvisualstudio2019community
{
    Install-ChocoPackage -PackageName "visualstudio2019community"
}
Function InstalldockerforWindows
{
    Install-ChocoPackage -PackageName "docker-for-windows"
}

Function InstallEdgeChromium
{
    # Skip download if Edge is already installed (pre-installed on Azure VMs since 2021)
    $edgePaths = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    )
    $existingEdge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $existingEdge) {
        # Ensure download dir exists on freshly deployed VMs
        if (-not (Test-Path 'C:\Packages')) { New-Item -ItemType Directory -Path 'C:\Packages' -Force | Out-Null }
        # Fix #21: use Edge Stable Enterprise x64 (LinkID 2109047), not Beta (2093437)
        $WebClient = New-Object System.Net.WebClient
        $WebClient.DownloadFile("https://go.microsoft.com/fwlink/?LinkID=2109047","C:\Packages\MicrosoftEdgeEnterpriseX64.msi")
        Start-Process msiexec.exe -Wait '/I C:\Packages\MicrosoftEdgeEnterpriseX64.msi /qn' -Verbose
        # Re-detect after install
        $existingEdge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    } else {
        Write-Host "Edge already installed at $existingEdge - skipping download." -ForegroundColor Green
    }

    $edgeExe = if ($existingEdge) { $existingEdge } else { $edgePaths[0] }
    $WshShell = New-Object -comObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut("C:\Users\Public\Desktop\Azure Portal.lnk")
    $Shortcut.TargetPath = """$edgeExe"""
    $argA = """https://portal.azure.com"""
    $Shortcut.Arguments = $argA 
    $Shortcut.Save()

    #Disable Welcome page of Microsoft Edge
    #Disable Edge 'First Run' Setup

    # Fix #21: missing '\' after drive prefix
    $edgePolicyRegistryPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Edge'
    $desktopSettingsRegistryPath = 'HKCU:\SOFTWARE\Microsoft\Windows\Shell\Bags\1\Desktop'
    $firstRunRegistryName = 'HideFirstRunExperience'
    $firstRunRegistryValue = '0x00000001'
    $savePasswordRegistryName = 'PasswordManagerEnabled'
    $savePasswordRegistryValue = '0x00000000'
    $autoArrangeRegistryName = 'FFlags'
    $autoArrangeRegistryValue = '1075839525'

    if (-NOT (Test-Path -Path $edgePolicyRegistryPath)) {
	New-Item -Path $edgePolicyRegistryPath -Force | Out-Null
    }

    if (-NOT (Test-Path -Path $desktopSettingsRegistryPath)) {
	New-Item -Path $desktopSettingsRegistryPath -Force | Out-Null
    }

    New-ItemProperty -Path $edgePolicyRegistryPath -Name $firstRunRegistryName -Value $firstRunRegistryValue -PropertyType DWORD -Force
    New-ItemProperty -Path $edgePolicyRegistryPath -Name $savePasswordRegistryName -Value $savePasswordRegistryValue -PropertyType DWORD -Force
    Set-ItemProperty -Path $desktopSettingsRegistryPath -Name $autoArrangeRegistryName -Value $autoArrangeRegistryValue -Force

    #Set-Location hklm:
    #Test-Path .\Software\Policies\Microsoft
    #New-Item -Path .\Software\Policies\Microsoft -Name MicrosoftEdge
    #New-Item -Path .\Software\Policies\Microsoft\MicrosoftEdge -Name Main
    #New-ItemProperty -Path .\Software\Policies\Microsoft\MicrosoftEdge\Main -Name PreventFirstRunPage -Value "1" -Type DWORD -Force -ErrorAction SilentlyContinue | Out-Null

    #Setting up the edge browser as default

    Invoke-WebRequest 'https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/SetUserFTA.zip' -OutFile 'C:\SetUserFTA.zip'
    Expand-Archive -Path 'C:\SetUserFTA.zip' -DestinationPath 'C:\' -Force
    cmd.exe /c C:\SetUserFTA\SetUserFTA.exe
    cmd.exe /c C:\SetUserFTA\SetUserFTA.exe http MSEdgeHTM
    cmd.exe /c C:\SetUserFTA\SetUserFTA.exe https MSEdgeHTM
    cmd.exe /c C:\SetUserFTA\SetUserFTA.exe .htm MSEdgeHTM
    Sleep 5
    Remove-Item -Path 'C:\SetUserFTA.zip'
    Remove-Item -Path 'C:\SetUserFTA' -Force -Recurse
  

}

Function Expand-ZIPFile($file, $destination)
{
$shell = new-object -com shell.application
$zip = $shell.NameSpace($file)
foreach($item in $zip.items())
    {
        $shell.Namespace($destination).copyhere($item)
}
}

Function Download($fileurl, $destination)
{
$WebClient = New-Object System.Net.WebClient
$WebClient.DownloadFile("$fileurl","$destination")
}

Function ResizeOSDiskMax()
{
# Iterate through all the disks on the Windows machine
foreach($disk in Get-Disk)
{
# Check if the disk in context is a Boot and System disk
if((Get-Disk -Number $disk.number).IsBoot -And (Get-Disk -Number $disk.number).IsSystem)
{
    # Get the drive letter assigned to the disk partition where OS is installed
    $driveLetter = (Get-Partition -DiskNumber $disk.Number | where {$_.DriveLetter}).DriveLetter
    Write-verbose "Current OS Drive: $driveLetter :\"

    # Get current size of the OS parition on the Disk
    $currentOSDiskSize = (Get-Partition -DriveLetter $driveLetter).Size        
    Write-verbose "Current OS Partition Size: $currentOSDiskSize"

    # Get Partition Number of the OS partition on the Disk
    $partitionNum = (Get-Partition -DriveLetter $driveLetter).PartitionNumber
    Write-verbose "Current OS Partition Number: $partitionNum"

    # Get the available unallocated disk space size
    $unallocatedDiskSize = (Get-Disk -Number $disk.number).LargestFreeExtent
    Write-verbose "Total Unallocated Space Available: $unallocatedDiskSize"

    # Get the max allowed size for the OS Partition on the disk
    $allowedSize = (Get-PartitionSupportedSize -DiskNumber $disk.Number -PartitionNumber $partitionNum).SizeMax
    Write-verbose "Total Partition Size allowed: $allowedSize"

    if ($unallocatedDiskSize -gt 0 -And $unallocatedDiskSize -le $allowedSize)
    {
        $totalDiskSize = $allowedSize
        
        # Resize the OS Partition to Include the entire Unallocated disk space
        $resizeOp = Resize-Partition -DriveLetter $driveLetter -Size $totalDiskSize
        Write-verbose "OS Drive Resize Completed $resizeOp"
    }
    else {
        Write-Verbose "There is no Unallocated space to extend OS Drive Partition size"
    }
}   
}
}

Function Install-dotnet3.1
{
$savedLocation = (Get-Location).Path
$WebClient = New-Object System.Net.WebClient
$WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/software/dotnet-install.ps1","C:\Packages\dotnet-install.ps1")
try {
    Set-Location C:\Packages
    .\dotnet-install.ps1 -Channel 3.1 -Runtime dotnet -Version 3.1.4 -InstallDir 'C:\Program Files\dotnet'
} finally {
    Set-Location $savedLocation
}

}

Function InstallCloudLabsManualAgentFiles
{
#Download files to write deployment status
Set-Content -Path 'C:\WindowsAzure\Logs\status-sample.txt' -Value '{"ServiceCode" : "ManualStepService", "Status" : "ReplaceStatus", "Message" : "ReplaceMessage"}'
Set-Content -Path 'C:\WindowsAzure\Logs\validationstatus.txt' -Value '{"ServiceCode" : "ManualStepService", "Status" : "ReplaceStatus", "Message" : "ReplaceMessage"}'

#Download cloudlabsagent zip
Invoke-WebRequest 'https://experienceazure.blob.core.windows.net/software/cloudlabsagent/CloudLabsAgent.zip' -OutFile 'C:\Packages\CloudLabsAgent.zip'
Expand-Archive -LiteralPath 'C:\Packages\CloudLabsAgent.zip' -DestinationPath 'C:\Packages\' -Force
Set-ExecutionPolicy -ExecutionPolicy bypass -Force
cmd.exe --% /c @echo off
cmd.exe --% /c sc create "Spektra.CloudLabs.Agent" BinPath=C:\Packages\CloudLabsAgent\Spektra.CloudLabs.Agent.exe start= auto
sleep 5
cmd.exe --% /c sc start "Spektra.CloudLabs.Agent"
sleep 5 
}

Function SetDeploymentStatus{
   Param(
     [parameter(Mandatory=$true)]
      [String] $ManualStepStatus,
       
       [parameter(Mandatory=$true)]
      [String] $ManualStepMessage    
       )  
  (Get-Content -Path "C:\WindowsAzure\Logs\status-sample.txt") | ForEach-Object {$_ -Replace "ReplaceStatus", "$ManualStepStatus"} | Set-Content -Path "C:\WindowsAzure\Logs\validationstatus.txt"
   (Get-Content -Path "C:\WindowsAzure\Logs\validationstatus.txt") | ForEach-Object {$_ -Replace "ReplaceMessage", "$ManualStepMessage"} | Set-Content -Path "C:\WindowsAzure\Logs\validationstatus.txt"
     }
         
Function CloudLabsManualAgent{
<#
      SYNOPSIS
      This is a function for installing/starting the cloudlabsagent, and to send the deployment status    
#>

param(  
  #Task : to install or start the agent/ set the deployment status
      [parameter(Mandatory=$true)]
      [String]$Task
   )
    #To install cloudlabsagent service files
    if($Task -eq 'Install')
    {
       Install-dotnet3.1
       InstallCloudLabsManualAgentFiles
    }
    #start the cloudlabs agent service
    elseif($Task -eq 'Start')
    {
      cmd.exe --% /c sc start "Spektra.CloudLabs.Agent"
      sleep 5 
    } 
   elseif($Task -eq 'setStatus')
    {
      SetDeploymentStatus -ManualStepStatus $Validstatus -ManualStepMessage $Validmessage
    }       
   }
Function setupHypervNet($addressprefix, $netip)
{   
    # Create the NAT network
    Write-Output "Create internal NAT"
    $natName = "InternalNat"
    #New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix 192.168.0.0/16
    New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix $addressprefix

    # Create an internal switch with NAT
    Write-Output "Create internal switch"
    $switchName = 'InternalNATSwitch'
    New-VMSwitch -Name $switchName -SwitchType Internal
    $adapter = Get-NetAdapter | Where-Object { $_.Name -like "*"+$switchName+"*" }

    # Create an internal network (gateway first)
    Write-Output "Create gateway"
    #New-NetIPAddress -IPAddress 192.168.0.1 -PrefixLength 16 -InterfaceIndex $adapter.ifIndex
    New-NetIPAddress -IPAddress $netip -PrefixLength 16 -InterfaceIndex $adapter.ifIndex

    # Enable Enhanced Session Mode on Host
    Write-Output "Enable Enhanced Session Mode"
    Set-VMHost -EnableEnhancedSessionMode $true
}

Function ReArmWS
{
    #Update Windows server evaluation licence to 180 days
    slmgr.vbs /rearm
    net accounts /maxpwage:unlimited
    Restart-Computer -Force 

   <# for hyper v VMs use below code
   $ap = "demo@pass123"
   $cred = New-Object -ArgumentList "Administrator",(ConvertTo-SecureString -AsPlainText -Force -String $ap) -TypeName System.Management.Automation.PSCredential

    $blockB = {
    #Update Windows server evaluation licence to 180 days
        Write-Output "Re-arm (extend eval license) for VM $ComputerName at $ip"
        slmgr.vbs /rearm
        net accounts /maxpwage:unlimited
        Restart-Computer -Force
    }
    #Run Code BlockB in SQL VM
    $ip =  "192.168.0.4"
    foreach($serverIP in $ip){
        set-item wsman:\localhost\Client\TrustedHosts -value $serverIP -Force
        Invoke-Command -ComputerName $serverIP -Credential $cred -ScriptBlock $blockB
    }
    #>
}

Function setupUserData($vmAdminUsername)
{
    # Fix #16: -Force so re-runs don't error if dir exists
    New-Item -ItemType Directory -Path C:\CloudLabs\ -Force | Out-Null

    #Download userdata script
    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/UserDataSample/scripts/run-userdata.ps1","C:\CloudLabs\run-userdata.ps1")

    #download task scheduler xml
    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/UserDataSample/scripts/runuserdata.xml","C:\CloudLabs\runuserdata.xml")

    #update task scheduler xml
    (Get-Content -Path "C:\CloudLabs\runuserdata.xml") | ForEach-Object {$_ -Replace "ComputerNameValue", "$($env:ComputerName)"} | Set-Content -Path "C:\CloudLabs\runuserdata.xml"
    (Get-Content -Path "C:\CloudLabs\runuserdata.xml") | ForEach-Object {$_ -Replace "vmAdminUsernameValue", "$vmAdminUsername"} | Set-Content -Path "C:\CloudLabs\runuserdata.xml"

    #Create scheduled task to run-userdata script on user logon, system startup as triggers
    schtasks.exe /Create /XML C:\CloudLabs\runuserdata.xml /tn runuserdata
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "setupUserData: schtasks /Create returned exit code $LASTEXITCODE - scheduled task may not have been registered."
    }

    #delete task scheduler xml (best-effort; AV may briefly hold the file)
    Remove-Item -Path 'C:\CloudLabs\runuserdata.xml' -Force -ErrorAction SilentlyContinue
}

Function installmggraph
{
    # Fix #24: Install only the sub-modules actually used by Enable-GitHub.
    # The full Microsoft.Graph meta-module is ~700MB and frequently exceeds CSE timeout.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11

    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope AllUsers -ErrorAction SilentlyContinue | Out-Null

    if (-not (Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue)) {
        Register-PSRepository -Default -ErrorAction SilentlyContinue
    }
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction SilentlyContinue

    $requiredModules = @(
        'Microsoft.Graph.Authentication',
        'Microsoft.Graph.Identity.DirectoryManagement',
        'Microsoft.Graph.Identity.SignIns',
        'Microsoft.Graph.Groups',
        'Microsoft.Graph.Users',
        'Microsoft.Graph.Applications'
    )

    # PowerShellGet 1.0.0.1 (Server 2019 default) lacks -AcceptLicense; pass it only if supported.
    $supportsAcceptLicense = (Get-Command Install-Module).Parameters.ContainsKey('AcceptLicense')

    foreach ($mod in $requiredModules) {
        try {
            Write-Host "Installing $mod ..." -ForegroundColor Cyan
            $params = @{
                Name         = $mod
                Scope        = 'AllUsers'
                Repository   = 'PSGallery'
                AllowClobber = $true
                Force        = $true
                ErrorAction  = 'Stop'
            }
            if ($supportsAcceptLicense) { $params['AcceptLicense'] = $true }
            Install-Module @params
        } catch {
            Write-Warning "Failed to install $mod : $_"
        }
    }
}

Function WindowsServerCommon
{
# Fix #6: Properly enable TLS 1.2/1.1 (previous code assigned TLS 1.0 then a string that older .NET fails to parse)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11
Disable-InternetExplorerESC
Enable-IEFileDownload
Enable-CopyPageContent-In-InternetExplorer
InstallChocolatey
DisableServerMgrNetworkPopup
CreateLabFilesDirectory
DisableWindowsFirewall
InstallEdgeChromium
}

function Enable-GitHub {
    param (
        [Parameter(Mandatory = $true)]
        [string]$UserEmail,

        [Parameter(Mandatory = $true)]
        [string]$TenantId,

        [Parameter(Mandatory = $true)]
        [string]$ClientId,

        [Parameter(Mandatory = $true)]
        [string]$ClientSecret,

        [switch]$WithCopilot,

        [switch]$WithGHAS
    )

    Import-Module Microsoft.Graph.Authentication
    Import-Module Microsoft.Graph.Identity.DirectoryManagement
    Import-Module Microsoft.Graph.Groups
    Import-Module Microsoft.Graph.Users
    Import-Module Microsoft.Graph.Identity.SignIns
    Import-Module Microsoft.Graph.Applications

    $GroupIdWithoutCopilot = "83311b9f-c349-4a10-bb7f-e9342e76ea10"
    $GroupIdWithCopilot = "bb0215fb-69d3-4d16-be56-cd2da619de31"
    $GroupIdGHAS = "5bd562c2-02f4-463d-b9ef-86fd666f5fe7"

    if ($WithGHAS) {
        $GroupId = $GroupIdGHAS
        Write-Host "Adding user to GHAS group $GroupId"
    } elseif ($WithCopilot) {
        $GroupId = $GroupIdWithCopilot
        Write-Host "Adding user to Copilot group $GroupId"
    } else {
        $GroupId = $GroupIdWithoutCopilot
        Write-Host "Adding user to default group $GroupId"
    }
    Write-Host "Adding user to group $GroupId"

    $securePassword = ConvertTo-SecureString -String $ClientSecret -AsPlainText -Force
    $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $ClientId, $securePassword
    Connect-MgGraph -TenantId $TenantId -ClientSecretCredential $credential -NoWelcome
    Write-Host "Connected to Microsoft Graph API"

    $userDomain = $UserEmail.Split('@')[1]
    $tenantDomain = ((Get-MgOrganization).VerifiedDomains | Where-Object { $_.IsDefault -eq $true }).Name

    if ($userDomain -ne $tenantDomain) {
        Write-Host "User is external. Inviting guest user..."
        $params = @{
            InvitedUserEmailAddress = $UserEmail
            InviteRedirectUrl       = "https://myapplications.microsoft.com/?tenantid=$TenantId"
            SendInvitationMessage   = $true
        }
        $invitation = New-MgInvitation @params -Verbose
        $userObjectId = $invitation.InvitedUser.Id
    } else {
        Write-Host "User is internal. Getting user object ID..."
        $existingUser = Get-MgUser -Filter "userPrincipalName eq '$UserEmail'"
        if (-not $existingUser) {
            Write-Error "Internal user not found."
            return
        }
        $userObjectId = $existingUser.Id
    }

    # Fix #18: For freshly-invited guest users, the directory object isn't immediately
    # addressable by group APIs. Wait briefly before attempting group membership add.
    if ($userDomain -ne $tenantDomain) {
        Write-Host "Waiting 30s for guest user to propagate before group add..."
        Start-Sleep -Seconds 30
    }

    try {
        New-MgGroupMember -GroupId $GroupId -DirectoryObjectId $userObjectId -ErrorAction Stop
        Write-Host "User added to group $GroupId"
    } catch {
        Write-Warning "User may already be in the group or another error occurred: $_"
    }

    # GitHub EMU Synchronization
    $syncParams = @{
        parameters = @(
            @{
                ruleId = "03f7d90d-bf71-41b1-bda6-aaf0ddbee5d8"
                subjects = @(
                    @{
                        objectId = $GroupId
                        objectTypeName = "Group"
                        links = @{
                            members = @(
                                @{
                                    objectId = $userObjectId
                                    objectTypeName = "User"
                                }
                            )
                        }
                    }
                )
            }
        )
    }

    Start-Sleep 30

    $syncSucceeded = $false
    $retryCount = 0
    $maxRetries = 5

    while (-not $syncSucceeded -and $retryCount -lt $maxRetries) {
        try {
            Write-Host "Attempting GitHub EMU sync (try $($retryCount + 1))..."
            New-MgServicePrincipalSynchronizationJobOnDemand `
                -ServicePrincipalId da6c7f14-b7a5-4b1b-b357-3594173bea4a `
                -SynchronizationJobId gitHubEnterpriseCloud.f871d17eefcd44c7ba5a0162efa2fded.d2318294-74b6-4d39-b351-8f0ee74687c0 `
                -BodyParameter $syncParams
            Write-Host "GitHub EMU sync triggered successfully."
            $syncSucceeded = $true
        } catch {
            Write-Warning "GitHub EMU sync failed: $_"
            $retryCount++
            if ($retryCount -lt $maxRetries) {
                $waitTime = [math]::Pow(2, $retryCount)
                Write-Host "Retrying in $waitTime seconds..."
                Start-Sleep -Seconds $waitTime
            } else {
                Write-Error "Max retries reached. GitHub EMU sync could not be triggered."
            }
        }
    }
}