<#
Deploy the public demo: the API (offline stub models, seeded data) on Azure Container Apps, and the UI on
Azure Static Web Apps. No Azure OpenAI, Search, Databricks or Cosmos is used, so no real data or secrets are exposed.

  .\infra\deploy-demo.ps1 -ResourceGroup rg-amllake-dev -Location uksouth -Suffix dm01

Run it from the repository root, after `az login`. Needs Docker running and Node installed. Safe to re-run: it
updates what exists. Names must be unique worldwide, so pick your own -Suffix.
#>
param(
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [string] $Location = "uksouth",
  [Parameter(Mandatory)] [string] $Suffix,
  [string] $StaticWebAppLocation = "westeurope"
)
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Run { & $args[0] $args[1..($args.Length - 1)]; if ($LASTEXITCODE -ne 0) { throw "command failed: $($args -join ' ')" } }

$acr = "consultaiacr$Suffix"          # letters and digits only
$env_name = "consultai-env"
$app = "consultai-api-$Suffix"
$swa = "consultai-web-$Suffix"
$image = "$acr.azurecr.io/consultai-api:latest"

Step "Providers"
foreach ($ns in "Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.OperationalInsights", "Microsoft.Web") {
  Run az provider register --namespace $ns --wait
}

Step "Container registry ($acr)"
az acr show --name $acr --resource-group $ResourceGroup *> $null
if ($LASTEXITCODE -ne 0) { Run az acr create --name $acr --resource-group $ResourceGroup --location $Location --sku Basic --admin-enabled true }

Step "Build and push the API image (locally, then to the registry)"
Run docker build -f infra/docker/Dockerfile.backend -t $image .
Run az acr login --name $acr
Run docker push $image

Step "Container Apps environment"
az containerapp env show --name $env_name --resource-group $ResourceGroup *> $null
if ($LASTEXITCODE -ne 0) { Run az containerapp env create --name $env_name --resource-group $ResourceGroup --location $Location }

Step "Static Web App for the UI ($swa)"
az staticwebapp show --name $swa --resource-group $ResourceGroup *> $null
if ($LASTEXITCODE -ne 0) { Run az staticwebapp create --name $swa --resource-group $ResourceGroup --location $StaticWebAppLocation --sku Free }
$webHost = az staticwebapp show --name $swa --resource-group $ResourceGroup --query defaultHostname -o tsv
$webUrl = "https://$webHost"
Write-Host "UI address: $webUrl"

Step "API container app ($app)"
$cred = az acr credential show --name $acr --query "{u:username,p:passwords[0].value}" -o json | ConvertFrom-Json
$settings = @("LLM_PROVIDER=stub", "AUTH_MODE=dev", "ENVIRONMENT=dev", "DEMO_SEED=true",
              "DATABASE_URL=sqlite:////tmp/consultai.db", "CORS_ORIGINS=$webUrl")
az containerapp show --name $app --resource-group $ResourceGroup *> $null
if ($LASTEXITCODE -ne 0) {
  Run az containerapp create --name $app --resource-group $ResourceGroup --environment $env_name --image $image `
    --registry-server "$acr.azurecr.io" --registry-username $cred.u --registry-password $cred.p `
    --target-port 8000 --ingress external --min-replicas 1 --max-replicas 1 --cpu 0.5 --memory 1.0Gi --env-vars @settings
} else {
  Run az containerapp update --name $app --resource-group $ResourceGroup --image $image --set-env-vars @settings
}
$apiHost = az containerapp show --name $app --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
$apiUrl = "https://$apiHost"
Write-Host "API address: $apiUrl"

Step "Build the UI against the API"
Push-Location frontend
$env:VITE_API_BASE_URL = $apiUrl
$env:VITE_AUTH_MODE = "dev"
Run npm ci --no-audit --no-fund
Run npm run build
Pop-Location

Step "Upload the UI"
$token = az staticwebapp secrets list --name $swa --resource-group $ResourceGroup --query properties.apiKey -o tsv
Run npx --yes "@azure/static-web-apps-cli" deploy ./frontend/dist --deployment-token $token --env production

Step "Done"
Write-Host "Open: $webUrl" -ForegroundColor Green
Write-Host "API health: $apiUrl/health"
