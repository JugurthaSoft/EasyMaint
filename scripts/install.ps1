# Installation d'EasyMaint sur un poste ou un serveur Windows (Docker Desktop).
# Depuis le dossier d'EasyMaint (par exemple C:\easymaint), dans PowerShell :
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1            installation
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Demo      + données de démonstration
# Le script peut être relancé sans risque : un fichier .env existant est conservé, une entreprise
# existante n'est pas recréée. Les mots de passe générés ne sont jamais affichés.
param([switch]$Demo)

Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host $text -ForegroundColor Red; exit 1 }
function NewSecret($length) {
  $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
  $bytes = New-Object byte[] $length
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}
function EnvValue($name, $default) {
  $line = Select-String -Path .env -Pattern "^$name=(.*)$" | Select-Object -First 1
  if ($line -and $line.Matches[0].Groups[1].Value) { return $line.Matches[0].Groups[1].Value.Trim() }
  return $default
}

Step "1/5 Vérification de Docker"
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker ne répond pas. Installez Docker Desktop, démarrez-le, puis relancez ce script." }
Write-Host "Docker est prêt."

Step "2/5 Configuration (fichier .env)"
if (Test-Path .env) {
  Write-Host "Fichier .env existant : conservé tel quel."
} else {
  $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Loopback|VirtualBox|VMware" } |
    Select-Object -First 1 -ExpandProperty IPAddress
  if (-not $ip) { $ip = "127.0.0.1" }
  $answer = Read-Host "Adresse IP de ce poste sur le réseau de l'usine [$ip]"
  if ($answer) { $ip = $answer.Trim() }
  $text = [System.IO.File]::ReadAllText((Resolve-Path .env.example))
  $text = $text -replace "(?m)^DJANGO_SECRET_KEY=.*$", "DJANGO_SECRET_KEY=$(NewSecret 60)"
  $text = $text -replace "(?m)^POSTGRES_PASSWORD=.*$", "POSTGRES_PASSWORD=$(NewSecret 32)"
  $text = $text -replace "(?m)^DJANGO_ALLOWED_HOSTS=.*$", "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,$ip"
  $text = $text -replace "(?m)^DJANGO_CSRF_TRUSTED_ORIGINS=.*$", "DJANGO_CSRF_TRUSTED_ORIGINS=http://${ip}:8000"
  $text = $text -replace "(?m)^EASYMAINT_REQUIREMENTS=.*$", "EASYMAINT_REQUIREMENTS=base"
  Write-Host "Langue d'EasyMaint pour toute l'entreprise (choix définitif) / EasyMaint language for the whole company:"
  Write-Host "  1 = Français    2 = English"
  $choice = Read-Host "Choix / Choice [1]"
  $language = if ($choice.Trim() -eq "2") { "en" } else { "fr" }
  if ($text -match "(?m)^EASYMAINT_LANGUAGE=") {
    $text = $text -replace "(?m)^EASYMAINT_LANGUAGE=.*$", "EASYMAINT_LANGUAGE=$language"
  } else {
    $text = $text.TrimEnd() + "`nEASYMAINT_LANGUAGE=$language`n"
  }
  Write-Host "Langue / language : $language"
  [System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), $text, (New-Object System.Text.UTF8Encoding $false))
  Write-Host "Fichier .env créé : clé secrète et mot de passe de la base générés automatiquement."
  Write-Host "Ne partagez jamais ce fichier." -ForegroundColor Yellow
}
$port = EnvValue "EASYMAINT_PORT" "8000"

Step "3/5 Construction et démarrage (plusieurs minutes la première fois)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "Le démarrage a échoué : voir les messages ci-dessus." }

Step "4/5 Attente de l'application"
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
  try {
    $response = Invoke-WebRequest "http://localhost:$port/compte/connexion/" -UseBasicParsing -TimeoutSec 5
    $ready = $response.StatusCode -eq 200
  } catch { Start-Sleep -Seconds 3 }
}
if (-not $ready) { Fail "L'application ne répond pas. Consultez : docker compose logs web" }
Write-Host "L'application répond."

Step "5/5 Entreprise et administrateur"
$counts = docker compose exec -T web python manage.py shell -c "from apps.core.models import Tenant; print('EM', Tenant.objects.count(), Tenant.objects.exclude(code='demo').count())" |
  Select-String -Pattern "EM (\d+) (\d+)" | Select-Object -Last 1
$create = $true
if (-not $counts) {
  Write-Host "Impossible de compter les entreprises existantes." -ForegroundColor Yellow
  $create = (Read-Host "Créer une entreprise maintenant ? (O/N)") -match "^[oOyY]"
} elseif ([int]$counts.Matches[0].Groups[2].Value -gt 0) {
  Write-Host "Une entreprise existe déjà : rien à créer."
  $create = $false
} elseif ([int]$counts.Matches[0].Groups[1].Value -gt 0) {
  Write-Host "Seule l'entreprise de démonstration existe."
  $create = (Read-Host "Créer votre propre entreprise maintenant ? (O/N)") -match "^[oOyY]"
}
if ($create) {
  $name = Read-Host "Raison sociale de l'entreprise"
  $code = Read-Host "Code court (minuscules, chiffres et tirets, par exemple usine-sfax)"
  $admin = Read-Host "Identifiant de l'administrateur [admin]"
  if (-not $admin) { $admin = "admin" }
  Write-Host "Choisissez le mot de passe de l'administrateur (10 caractères minimum, saisie masquée) :"
  docker compose exec web python manage.py create_tenant --name "$name" --code "$code" --admin "$admin"
  if ($LASTEXITCODE -ne 0) { Fail "Création refusée (voir le message). Relancez le script pour réessayer." }
}
if ($Demo) {
  $secure = Read-Host "Mot de passe des comptes de démonstration" -AsSecureString
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  docker compose exec -T web python manage.py load_demo --password "$plain"
}

$hostIp = (EnvValue "DJANGO_ALLOWED_HOSTS" "localhost").Split(",") | ForEach-Object { $_.Trim() } |
  Where-Object { $_ -and $_ -notin @("localhost", "127.0.0.1", "web") } | Select-Object -Last 1
Write-Host "`nEasyMaint est installé." -ForegroundColor Green
Write-Host "Sur ce poste : http://localhost:$port"
if ($hostIp) {
  Write-Host "Depuis les autres postes de l'usine : http://${hostIp}:$port"
} else {
  Write-Host "Accès depuis les autres postes : ajoutez l'adresse IP de ce poste dans DJANGO_ALLOWED_HOSTS et DJANGO_CSRF_TRUSTED_ORIGINS du fichier .env (voir docs/installation.md)."
}
Write-Host "Sauvegarde automatique chaque nuit dans le dossier « sauvegardes » : copiez-le régulièrement hors du serveur."
