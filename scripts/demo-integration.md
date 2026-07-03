# demo.ps1 integration

Add the three params to the `Param()` block:

```powershell
[string]$SidecarEventID,
[string]$SidecarEndpoint,
[string]$SidecarKey
```

Add one line after the choco installs (requires InstallSidecarAgent merged
into cloudlabs-windows-functions.ps1):

```powershell
InstallSidecarAgent -SidecarEventID $SidecarEventID -SidecarEndpoint $SidecarEndpoint -SidecarKey $SidecarKey -DeploymentID $DeploymentID
```
