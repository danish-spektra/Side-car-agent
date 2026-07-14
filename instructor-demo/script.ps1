Param (
    [Parameter(Mandatory = $true)]
    [string]
    $AzureUserName,
    [string]
    $AzurePassword,
    [string]
    $AzureTenantID,
    [string]
    $AzureSubscriptionID,
    [string]
    $ODLID,
    [string]
    $DeploymentID,
    [string]
    $adminUsername,
    [string]
    $adminPassword,
    [string]
    $trainerUserName,
    [string]
    $trainerUserPassword
)

Start-Transcript -Path C:\WindowsAzure\Logs\CloudLabsCustomScriptExtension.txt -Append
[Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls
[Net.ServicePointManager]::SecurityProtocol = "tls12, tls11, tls"

#Import Common Functions
# CustomScriptExtension downloads all fileUris flat into the script's own folder,
# so resolve the common functions relative to this script (not the CWD / a subfolder).
$commonscriptpath = Join-Path $PSScriptRoot "cloudlabs-windows-functions.ps1"
if (-not (Test-Path $commonscriptpath)) {
    $commonscriptpath = Join-Path $PSScriptRoot "cloudlabs-common\cloudlabs-windows-functions.ps1"
}
. $commonscriptpath

# Run Imported functions from cloudlabs-windows-functions.ps1
WindowsServerCommon

InstallAzCLI
InstallAzPowerShellModule
InstallModernVmValidator
InstallGitTools
InstallPython
Install-ChocoPackage -PackageName "golang"
InstallVSCode

# Refresh PATH in this session so 'code' is usable right away, then add the Python extension
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
code --install-extension ms-python.python --force

CreateCredFile $AzureUserName $AzurePassword $AzureTenantID $AzureSubscriptionID $DeploymentID

Enable-CloudLabsEmbeddedShadow $adminUsername $trainerUserName $trainerUserPassword

# Azure Developer CLI - needed to run `azd up` for the instructor portal
iwr -useb https://aka.ms/install-azd.ps1 | iex

# Clone only the main branch of the instructor portal repo into C:\LabFiles
$repoPath = "C:\LabFiles\Side-car-agent"
if (Test-Path $repoPath) { Remove-Item -Path $repoPath -Recurse -Force }
git clone --branch main --single-branch https://github.com/danish-spektra/Side-car-agent.git $repoPath

# ponytail: azd up needs an interactive `azd auth login`, so it isn't run here -
# the instructor runs it from C:\LabFiles\Side-car-agent after logging in.

Stop-Transcript

Restart-Computer -Force
