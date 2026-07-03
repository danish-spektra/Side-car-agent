# CloudLabs Lab Assistant sidecar agent.
# Merge into cloudlabs-windows-functions.ps1; call from the lab's logon script:
#   InstallSidecarAgent -SidecarEventID $SidecarEventID -SidecarEndpoint $SidecarEndpoint -SidecarKey $SidecarKey -DeploymentID $DeploymentID
Function InstallSidecarAgent
{
    Param (
        [Parameter(Mandatory = $true)][string]$SidecarEventID,
        [Parameter(Mandatory = $true)][string]$SidecarEndpoint,
        [Parameter(Mandatory = $true)][string]$SidecarKey,
        [string]$DeploymentID = $env:ComputerName
    )
    $dir = 'C:\CloudLabs\Sidecar'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    # 1. Fetch the agent from the orchestrator itself
    Invoke-WebRequest "$SidecarEndpoint/download/sidecar.zip" -OutFile "$dir\sidecar.zip" -UseBasicParsing
    Expand-Archive -LiteralPath "$dir\sidecar.zip" -DestinationPath $dir -Force

    # 2. Stamp per-event config (CreateCredFile idiom, but JSON)
    @{
        endpoint      = $SidecarEndpoint
        event_id      = $SidecarEventID
        key           = $SidecarKey
        deployment_id = $DeploymentID
    } | ConvertTo-Json | Set-Content "$dir\config.json" -Encoding ascii

    # 3. Run at every logon (Enable-CloudLabsEmbeddedShadow idiom)
    #    ponytail: scheduled task instead of a Windows service — zero service
    #    plumbing in the binary; upgrade to sc create if lifecycle control is needed.
    $Action  = New-ScheduledTaskAction -Execute "$dir\sidecar.exe"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName 'CloudLabsLabAssistant' -Action $Action `
        -Trigger $Trigger -RunLevel Limited -Force
    Start-Process "$dir\sidecar.exe" -WindowStyle Hidden

    # 4. Desktop shortcut to the local UI
    Set-Content 'C:\Users\Public\Desktop\Lab Assistant.url' @'
[InternetShortcut]
URL=http://127.0.0.1:7788
'@
}
