targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string
// Pin the newest GA chat model available in the region at deploy time.
// gpt-4o is the safe default; override with e.g. GPT-5.x names once confirmed GA.
param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-11-20'
param chatDeploymentName string = 'chat'
@secure()
param instructorKey string = ''
param rateLimitQuestions int = 10
param rateLimitWindowSeconds int = 600
param eventTokenBudget int = 2000000

var suffix = uniqueString(resourceGroup().id, environmentName)

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'labasst${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'labasst-openai-${suffix}'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'labasst-openai-${suffix}'
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: chatDeploymentName
  sku: { name: 'Standard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: 'labasst-plan-${suffix}'
  location: location
  sku: { name: 'B1' }
  kind: 'linux'
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2023-01-01' = {
  name: 'labasst-${suffix}'
  location: location
  tags: { 'azd-service-name': 'orchestrator' }
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
      appSettings: [
        { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: openai.listKeys().key1 }
        { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
        { name: 'STORAGE_BACKEND', value: 'blob' }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'INSTRUCTOR_KEY', value: instructorKey }
        { name: 'RATE_LIMIT_QUESTIONS', value: string(rateLimitQuestions) }
        { name: 'RATE_LIMIT_WINDOW_SECONDS', value: string(rateLimitWindowSeconds) }
        { name: 'EVENT_TOKEN_BUDGET', value: string(eventTokenBudget) }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
      ]
    }
    httpsOnly: true
  }
}

output ORCHESTRATOR_URL string = 'https://${site.properties.defaultHostName}'
