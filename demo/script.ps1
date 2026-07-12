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
    $InstallCloudLabsShadow,

    [string]
    $DeploymentID,

    [string]
    $vmAdminUsername,

    [string]
    $vmAdminPassword,

    [string]
    $trainerUserName,

    [string]
    $trainerUserPassword
)

Start-Transcript -Path C:\WindowsAzure\Logs\CloudLabsCustomScriptExtension.txt -Append
[Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls
[Net.ServicePointManager]::SecurityProtocol = "tls12, tls11, tls" 

Function CreateCredFile($AzureUserName, $AzurePassword, $AzureTenantID, $AzureSubscriptionID, $DeploymentID) {
    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/AzureCreds.txt", "C:\LabFiles\AzureCreds.txt")
    $WebClient.DownloadFile("https://experienceazure.blob.core.windows.net/templates/cloudlabs-common/AzureCreds.ps1", "C:\LabFiles\AzureCreds.ps1")
    
    New-Item -ItemType directory -Path C:\LabFiles -force

    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object { $_ -Replace "AzureUserNameValue", "$AzureUserName" } | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object { $_ -Replace "AzurePasswordValue", "$AzurePassword" } | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object { $_ -Replace "AzureTenantIDValue", "$AzureTenantID" } | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object { $_ -Replace "AzureSubscriptionIDValue", "$AzureSubscriptionID" } | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
    (Get-Content -Path "C:\LabFiles\AzureCreds.txt") | ForEach-Object { $_ -Replace "DeploymentIDValue", "$DeploymentID" } | Set-Content -Path "C:\LabFiles\AzureCreds.txt"
             
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object { $_ -Replace "AzureUserNameValue", "$AzureUserName" } | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object { $_ -Replace "AzurePasswordValue", "$AzurePassword" } | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object { $_ -Replace "AzureTenantIDValue", "$AzureTenantID" } | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object { $_ -Replace "AzureSubscriptionIDValue", "$AzureSubscriptionID" } | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"
    (Get-Content -Path "C:\LabFiles\AzureCreds.ps1") | ForEach-Object { $_ -Replace "DeploymentIDValue", "$DeploymentID" } | Set-Content -Path "C:\LabFiles\AzureCreds.ps1"

    Copy-Item "C:\LabFiles\AzureCreds.txt" -Destination "C:\Users\Public\Desktop"
}

CreateCredFile $AzureUserName $AzurePassword $AzureTenantID $AzureSubscriptionID $DeploymentID

Function updateVMShadowFile {
    #Replace vmAdminUsernameValue with VM Admin UserName in script content 
    $drivepath = "C:\Users\Public\Documents"
(Get-Content -Path "$drivepath\Shadow.ps1") | ForEach-Object { $_ -Replace "vmAdminUsernameValue", "$vmAdminUsername" } | Set-Content -Path "$drivepath\Shadow.ps1"
    #Update random password
    net user $trainerUserName $trainerUserPassword
}
updateVMShadowFile

#Install Cloudlabs Modern VM (Windows Server 2012,2016,2019, Windows 10) Validator
Function InstallModernVmValidator
{   #dotnet core is pre-req for vmagent or validator
    #Create C:\CloudLabs\Validator directory
    New-Item -ItemType directory -Path C:\CloudLabs\Validator -Force
    Invoke-WebRequest 'https://experienceazure.blob.core.windows.net/software/vm-validator/VMAgent.zip' -OutFile 'C:\CloudLabs\Validator\VMAgent.zip'
    Expand-Archive -LiteralPath 'C:\CloudLabs\Validator\VMAgent.zip' -DestinationPath 'C:\CloudLabs\Validator' -Force
    Set-ExecutionPolicy -ExecutionPolicy bypass -Force
    cmd.exe --% /c @echo off
    cmd.exe --% /c sc create "Spektra CloudLabs VM Agent" BinPath=C:\CloudLabs\Validator\VMAgent\Spektra.CloudLabs.VMAgent.exe start= auto
    cmd.exe --% /c sc start "Spektra CloudLabs VM Agent"
}
InstallModernVmValidator

#SetEnvironmentVariable
[System.Environment]::SetEnvironmentVariable('AZURE_RESOURCE_GROUP',$env_name,[System.EnvironmentVariableTarget]::Machine)
[System.Environment]::SetEnvironmentVariable('AZURE_RESOURCE_GROUP',$env_name,[System.EnvironmentVariableTarget]::User)

#Clone GitHub Repo
cd C:\LabFiles
git clone https://github.com/CloudLabsAI-Azure/openai.git
git clone https://github.com/CloudLabsAI-Azure/OpenAIWorkshop-HR-Copilot-Automation
Rename-Item -Path "C:\LabFiles\OpenAIWorkshop-HR-Copilot-Automation" -NewName "OpenAIWorkshop"

#Installing pip packages
cd C:\LabFiles\OpenAIWorkshop\scenarios\incubations\copilot

pip install -r requirements.txt
pip install azure-appconfiguration
pip install azure-mgmt-compute
pip install azure-mgmt-web
pip install azure-identity
pip install azure-mgmt-search
pip install azure-search-documents
pip install --upgrade streamlit
pip install azure-search-documents==11.4.0b6

Stop-Transcript
Disable-ScheduledTask -TaskName "runuserdata"
Stop-ScheduledTask -TaskName "runuserdata"