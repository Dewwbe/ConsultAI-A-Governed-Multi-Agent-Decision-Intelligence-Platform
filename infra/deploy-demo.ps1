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
  [string] $StaticWebAppLocation = ""   # empty: try each Static Web Apps region until one is accepted
)
# Not "Stop": Windows PowerShell 5 would abort on any text az writes to stderr (warnings included), even on success.
# Every step is checked by its exit code in Run instead.
$ErrorActionPreference = "Continue"
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
# True if an `az ... show` finds the resource. A "not found" is an expected answer here, not a failure, and Windows
# PowerShell 5 would otherwise treat az's error text as fatal.
function Exists {
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  & $args[0] $args[1..($args.Length - 1)] 2>$null | Out-Null
  $found = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $old
  return $found
}
function Run { & $args[0] $args[1..($args.Length - 1)]; if ($LASTEXITCODE -ne 0) { throw "command failed: $($args -join ' ')" } }

$acr = "consultaiacr$Suffix"          # letters and digits only
$env_name = "consultai-env"
$app = "consultai-api-$Suffix"
$swa = "consultai-web-$Suffix"
# a new tag per deploy, so Container Apps always starts a new revision with the new code
$image = "$acr.azurecr.io/consultai-api:" + (Get-Date -Format "yyyyMMdd-HHmmss")

Step "Providers"
foreach ($ns in "Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.OperationalInsights", "Microsoft.Web") {
  Run az provider register --namespace $ns --wait
}

Step "Container registry ($acr)"
if (-not (Exists az acr show --name $acr --resource-group $ResourceGroup)) { Run az acr create --name $acr --resource-group $ResourceGroup --location $Location --sku Basic --admin-enabled true }

Step "Build and push the API image (locally, then to the registry)"
Run docker build -f infra/docker/Dockerfile.backend -t $image .
Run az acr login --name $acr
# A slow or flaky connection can time out part-way through a large upload. Layers already sent are kept, so retrying
# only sends what is left.
$pushed = $false
foreach ($attempt in 1..5) {
  docker push $image
  if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
  Write-Host "push attempt $attempt failed; retrying in 10 s" -ForegroundColor Yellow
  Start-Sleep -Seconds 10
  az acr login --name $acr | Out-Null   # the registry token can expire during a long upload
}
if (-not $pushed) { throw "docker push failed 5 times; check your connection and run the script again" }

Step "Container Apps environment"
if (-not (Exists az containerapp env show --name $env_name --resource-group $ResourceGroup)) { Run az containerapp env create --name $env_name --resource-group $ResourceGroup --location $Location }

Step "Static Web App for the UI ($swa)"
if (-not (Exists az staticwebapp show --name $swa --resource-group $ResourceGroup)) {
  # Static Web Apps exists in only a few regions, and some subscriptions are refused in some of them. The region only
  # holds the app's settings: the site itself is served from Azure's global edge, so any region is fine for visitors.
  $regions = if ($StaticWebAppLocation) { @($StaticWebAppLocation) } else { @("westeurope", "eastus2", "centralus", "westus2", "eastasia") }
  $created = $false
  foreach ($r in $regions) {
    Write-Host "trying $r"
    az staticwebapp create --name $swa --resource-group $ResourceGroup --location $r --sku Free --output none
    if ($LASTEXITCODE -eq 0) { $created = $true; Write-Host "created in $r"; break }
  }
  if (-not $created) { throw "no Static Web Apps region accepted this subscription: $($regions -join ', ')" }
}
$webHost = az staticwebapp show --name $swa --resource-group $ResourceGroup --query defaultHostname -o tsv
if (-not $webHost) { throw "could not read the Static Web App address" }
$webUrl = "https://$webHost"
Write-Host "UI address: $webUrl"

Step "API container app ($app)"
$cred = az acr credential show --name $acr --query "{u:username,p:passwords[0].value}" -o json | ConvertFrom-Json
if (-not $cred.p) { throw "could not read the registry credentials" }
$settings = @("LLM_PROVIDER=stub", "AUTH_MODE=dev", "ENVIRONMENT=dev", "DEMO_SEED=true",
              "DATABASE_URL=sqlite:////tmp/consultai.db", "CORS_ORIGINS=$webUrl")
if (-not (Exists az containerapp show --name $app --resource-group $ResourceGroup)) {
  Run az containerapp create --name $app --resource-group $ResourceGroup --environment $env_name --image $image `
    --registry-server "$acr.azurecr.io" --registry-username $cred.u --registry-password $cred.p `
    --target-port 8000 --ingress external --min-replicas 1 --max-replicas 1 --cpu 0.5 --memory 1.0Gi --env-vars @settings
} else {
  Run az containerapp update --name $app --resource-group $ResourceGroup --image $image --set-env-vars @settings
}
$apiHost = az containerapp show --name $app --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
if (-not $apiHost) { throw "could not read the API address" }
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
