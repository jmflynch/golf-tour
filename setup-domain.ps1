# Points a Wix-registered domain at this GitHub Pages site, end to end.
#
#   powershell -ExecutionPolicy Bypass -File setup-domain.ps1
#
# Prompts for the API key and domain, shows you the plan, waits for your OK,
# then writes DNS at Wix and sets the custom domain on GitHub.
# Nothing is stored on disk and nothing lands in your shell history.

$ErrorActionPreference = "Stop"
$py = "C:\Users\Jeremy\AppData\Local\Programs\Python\Python312\python.exe"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host ""
Write-Host "  Wix -> GitHub Pages domain setup" -ForegroundColor Cyan
Write-Host "  --------------------------------"
Write-Host ""
Write-Host "  Use a FRESH API key. If you have pasted one anywhere, revoke it first:"
Write-Host "  Wix dashboard -> Settings -> API Keys"
Write-Host ""

$env:WIX_API_KEY = Read-Host "  Wix API key"
if (-not $env:WIX_API_KEY) { Write-Host "  No key given, stopping." -ForegroundColor Red; exit 1 }

$env:WIX_ACCOUNT_ID = Read-Host "  Wix account ID [press Enter for 0c5099d3-1c07-494b-9671-d907077f6dfd]"
if (-not $env:WIX_ACCOUNT_ID) { $env:WIX_ACCOUNT_ID = "0c5099d3-1c07-494b-9671-d907077f6dfd" }

$env:GOLF_DOMAIN = Read-Host "  Domain (bare - no https, no www)"
if (-not $env:GOLF_DOMAIN) { Write-Host "  No domain given, stopping." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Reading your DNS zone..." -ForegroundColor Cyan
& $py wix_dns.py
if ($LASTEXITCODE -ne 0) { Write-Host "  Stopped - see the error above." -ForegroundColor Red; exit 1 }

Write-Host ""
$ok = Read-Host "  Write these DNS records? (y/N)"
if ($ok -ne "y") { Write-Host "  Cancelled. Nothing changed." -ForegroundColor Yellow; exit 0 }

& $py wix_dns.py --apply
if ($LASTEXITCODE -ne 0) { Write-Host "  DNS write failed - see above." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Setting the custom domain on GitHub..." -ForegroundColor Cyan
gh api -X PUT repos/jmflynch/golf-tour/pages -f "cname=$($env:GOLF_DOMAIN)" -f "source[branch]=main" -f "source[path]=/docs"
if ($LASTEXITCODE -ne 0) {
  Write-Host "  GitHub step failed. Set it by hand instead:" -ForegroundColor Yellow
  Write-Host "  https://github.com/jmflynch/golf-tour/settings/pages"
} else {
  Write-Host "  Custom domain set." -ForegroundColor Green
}

# don't leave the key in the session
$env:WIX_API_KEY = $null

Write-Host ""
Write-Host "  Done. DNS takes 10-60 minutes to propagate." -ForegroundColor Green
Write-Host "  Check progress:  gh api repos/jmflynch/golf-tour/pages"
Write-Host "  Then tick 'Enforce HTTPS' once the certificate is issued."
Write-Host ""
