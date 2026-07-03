# Wiring the Lab Assistant into a CloudLabs deployment

## 1. deploy.json — add parameters

```json
"sidecarEventID":  { "type": "string" },
"sidecarEndpoint": { "type": "string" },
"sidecarKey":      { "type": "securestring" }
```

## 2. deploy.json — add variable (next to `cloudlabsCommon`)

```json
"sidecarArgs": "[concat(' -SidecarEventID ', parameters('sidecarEventID'), ' -SidecarEndpoint ', parameters('sidecarEndpoint'), ' -SidecarKey ', parameters('sidecarKey'))]"
```

## 3. deploy.json — thread into commandToExecute

```json
"commandToExecute": "[concat('powershell.exe -ExecutionPolicy Unrestricted -File <labscript>.ps1', variables('cloudlabsCommon'), variables('Enable-CloudLabsEmbeddedShadow'), variables('sidecarArgs'))]"
```

## 4. Where the values come from

The instructor portal (step 3 on the page) prints exactly these three values
after ingest. Paste them into the CloudLabs template parameters before
launching the event.
